from flask import abort, Flask, request, render_template, redirect, session, url_for, Markup, make_response
import spotipy
import spotipy.util as util
import json
import requests
import os
from dotenv import load_dotenv
import logging
import secrets
import string
import base64
from urllib.parse import urlencode

project_folder = os.path.expanduser('/tempotraining')
load_dotenv(os.path.join(project_folder, '.env'))

app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY')


# DO NOT PUBLISH CREDENTIALS!
CLIENT_ID = os.getenv('CLIENT_ID')
CLIENT_SECRET = os.getenv('CLIENT_SECRET')
REDIRECT_URI = os.getenv('REDIRECT_URI')

client_creds = f"{CLIENT_ID}:{CLIENT_SECRET}"
client_creds_b64 = base64.b64encode(client_creds.encode())



# Spotify Endpoints
AUTH_URL = 'https://accounts.spotify.com/authorize'
TOKEN_URL = 'https://accounts.spotify.com/api/token'


@app.route("/")
def index():
	return render_template("index.html")

@app.route("/<login>")
# Log in user and authorize app use
def login(login):
	

	# Create a random string for state
	state = ''.join(
		secrets.choice(string.ascii_uppercase + string.digits) for _ in range(16)
		)
	#Payload for spotify response
	payload = {
		"client_id" : CLIENT_ID,
		"response_type" : "code",
		"redirect_uri" : REDIRECT_URI,
		"state" : state,
		"scope" : "playlist-modify-public",
		"show_dialog" : "true"
		}
	res = make_response(redirect(f'{AUTH_URL}/?{urlencode(payload)}'))
	res.set_cookie('spotify_auth_state', state)

	return res


@app.route("/callback")
def callback():
	error = request.args.get('error')
	code = request.args.get('code')
	state = request.args.get('state')
	stored_state = request.cookies.get('spotify_auth_state')

	# Check state
	if state is None or state != stored_state:
		app.logger.error('Error message: %s', repr(error))
		app.logger.error('State mismatch: %s != %s', stored_state, state)
		abort(400)

	# Request tokens with code obtained from Spotify
	payload = {
		"grant_type" : "authorization_code",
		"code" : code,
		"redirect_uri" : REDIRECT_URI
		}
	token_headers = {
		"Authorization" : f"Basic {client_creds_b64.decode()}"
		}

	res = requests.post(TOKEN_URL, data=payload, headers=token_headers)
	res_data = res.json()

	if res_data.get('error') or res.status_code != 200:
		app.logger.error(
			'Failed to receive token: %s',
			res_data.get('error', 'No error information received.'),
		)
		abort(res.status_code)

	# Load tokens into session
	session['tokens'] = {
		'access_token': res_data.get('access_token'),
		'refresh_token': res_data.get('refresh_token'),
	}

	return redirect(url_for('make_playlist'))

@app.route("/make-playlist")
def make_playlist():

	return render_template("make-playlist/index.html")

@app.route("/your-playlist")
def show_playlist():
	username = ''
	token = session['tokens'].get('access_token')
	desired_artist = request.args.get("artist_to_search")
	desired_bpm = int(request.args.get("bpm_to_search"))

	sp = spotipy.Spotify(auth=token)

	# Handle no artist entered in form
	if not desired_artist:
		return redirect(url_for("index"))
	
	# Search for artist 
	desired_artist_results = sp.search(q="artist:" + desired_artist, type="artist")	
	# Handle artist not found
	if len(desired_artist_results["artists"]["items"]) == 0:
		return redirect(url_for("artist_not_found"))

	# Get artist info	
	desired_artist_entry = desired_artist_results["artists"]["items"][0]
	artist_name = desired_artist_entry["name"]
	artist_uri = desired_artist_entry["uri"]
	artist_image_url = desired_artist_entry["images"][0]["url"]	
	

	# Get username
	user_info_url = "https://api.spotify.com/v1/me"
	user_header = {
		"Authorization" : f"Bearer {token}"
		}
	r = requests.get(user_info_url, headers = user_header)
	user_data = r.json()
	username = user_data['id']

	# Create Playlist
	playlist_name = "Tempo training, inspired by " + artist_name
	sp.trace = False
	playlist = sp.user_playlist_create(username, playlist_name)
	playlist_id = playlist["id"]
	

	# Make list of tracks
	list_of_tracks = []
	
	# Add artist top tracks to list of tracks
	# Be mindful of number of tracks b/c API limits
	artist_top_tracks = sp.artist_top_tracks(artist_uri)
	song_count = 0
	for track in artist_top_tracks["tracks"]:
		if song_count < 5:
			# Check tempo of track before adding to list of tracks
			track_info = sp.audio_features(track["id"])
			tempo = track_info[0]['tempo']
			if (tempo > (desired_bpm-3) and tempo < (desired_bpm+3)) or (tempo*2 > (desired_bpm-3) and tempo*2 < (desired_bpm+3)):
				list_of_tracks.append(track["id"])
				song_count += 1

	# Make a list of artist top track ids
	top_tracks = artist_top_tracks["tracks"]
	track_recommendations = []
	for track in top_tracks:
		track_recommendations.append(track['id'])
	 
	top5 = track_recommendations[:5]
	top10 = track_recommendations[6:10]

	# Define funtion for getting recommendations based on top tracks (max 5 track seeds)
	def get_recommendations(tracks):
		recommendations = sp.recommendations(seed_tracks = tracks, limit=100)
		var = recommendations['tracks']
		list_of_100_recommendations = []
		for track in var:
			list_of_100_recommendations.append(track['id'])
		# Create a list of audio features for 100 recommended tracks
		multiple_features = sp.audio_features(tracks=list_of_100_recommendations)
		for item in multiple_features:
			tempo = item['tempo']
			track_id = item['id']
			# If tempo is within range, add id to the playlist
			if (tempo > (desired_bpm-3) and tempo < (desired_bpm+3)) or (tempo*2 > (desired_bpm-3) and tempo*2 < (desired_bpm+3)):
				list_of_tracks.append(track_id)


	# Get related artists
	related_artists = sp.artist_related_artists(artist_uri)
	artist_to_recommend = related_artists["artists"]
	#Make a list of related artist ids
	artist_recommendations = []
	for artists in artist_to_recommend:
	        artist_recommendations.append(artists["id"])
	        
	artist_top5 = artist_recommendations[:5]
	artist_top10 = artist_recommendations[6:10]
	artist_top15 = artist_recommendations[11:15]
	artist_top20 = artist_recommendations[16:20]

	# Define function for getting recommendations based on related artists (max 5 artist seeds)
	def get_artist_recommendations(artist):
		recommendations = sp.recommendations(seed_artists = artist, limit=100)
		var = recommendations['tracks']
		list_of_100_recommendations = []
		for track in var:
			list_of_100_recommendations.append(track['id'])
		# Create a list of audio features for 100 recommended tracks
		multiple_features = sp.audio_features(tracks=list_of_100_recommendations)
		for item in multiple_features:
			tempo = item['tempo']
			track_id = item['id']
			# If tempo is within range, add id to the playlist
			if (tempo > (desired_bpm-3) and tempo < (desired_bpm+3)) or (tempo*2 > (desired_bpm-3) and tempo*2 < (desired_bpm+3)):
				list_of_tracks.append(track_id)


	get_recommendations(top5)
	get_recommendations(top10)
	get_artist_recommendations(artist_top5)
	get_artist_recommendations(artist_top10)
	get_artist_recommendations(artist_top15)
	get_artist_recommendations(artist_top20)

	
	# Add list of tracks to playlist
	add_tracks_to_playlist = sp.user_playlist_add_tracks(username, playlist_id, list_of_tracks)
		
	# Make playlist iframe href
	playlist_iframe_href = "https://open.spotify.com/embed?uri=spotify:user:" + username + ":playlist:" + playlist_id + "&theme=white"
				
	return render_template("your-playlist/index.html", artist_name=artist_name, artist_image_url=artist_image_url, playlist_iframe_href=playlist_iframe_href)

@app.route("/artist-not-found/")
def artist_not_found():
	return render_template("/artist-not-found/index.html")

@app.errorhandler(404)
def page_not_found(e):
	return render_template("/error-pages/404.html")

if __name__ == "__main__":
	app.debug = True
	app.run()