import flask, json, os, re, sys, arrow, requests, psycopg2, urllib

api_key = os.getenv('GOOGLE_API_KEY', None)

def setup():
	default_dsn = 'dbname=elections'
	db_dsn = os.getenv('POSTGRES_DSN', default_dsn)
	db = psycopg2.connect(db_dsn)
	cur = db.cursor()

	cur.execute('''
		CREATE TABLE IF NOT EXISTS google_civic_info (
			name VARCHAR(255) PRIMARY KEY,
			value TEXT,
			updated TIMESTAMP
		)
	''')
	db.commit()

def cache_get(name, ttl):

	utc = arrow.utcnow()
	expires = utc.shift(seconds=-ttl).format('YYYY-MM-DD HH:mm:ss')

	cur = flask.g.db.cursor()
	cur.execute('''
		SELECT value
		FROM google_civic_info
		WHERE name = %s
		  AND updated > %s
	''', (name, expires))

	rsp = cur.fetchone()
	if rsp:
		return rsp[0]
	else:
		return None

def cache_set(name, value):

	utc = arrow.utcnow()
	updated = utc.format('YYYY-MM-DD HH:mm:ss')

	cur = flask.g.db.cursor()

	cur.execute('''
		DELETE FROM google_civic_info
		WHERE name = %s
	''', (name,))

	cur.execute('''
		INSERT INTO google_civic_info
		(name, value, updated)
		VALUES (%s, %s, %s)
	''', (name, value, updated))

	flask.g.db.commit()

def get_elections():

	global api_key

	ttl = 60 * 60
	cached = cache_get('elections', ttl)

	if cached:
		rsp = json.loads(cached)
	else:
		url = "https://www.googleapis.com/civicinfo/v2/elections?key=%s" % api_key
		rsp = requests.get(url)
		cache_set('elections', rsp.text)
		rsp = rsp.json()

	return rsp['elections']

def get_available_elections(ocd_ids):
	elections = get_elections()
	available = []
	for el in elections:

		election_id = el["id"]
		ocd_id = el['ocdDivisionId']

		# VIP Test Election
		if election_id == "2000":
			continue

		if ocd_id in available:
			continue

		if ocd_id in ocd_ids:
			available.append(ocd_id)
		elif election_id == "6000" and election_available(6000, ocd_ids):
			available.append(ocd_id)
	return available

def get_election_id(ocd_id):
	elections = get_elections()
	for el in elections:
		if ocd_id.startswith(el['ocdDivisionId']) and el['id'] != "2000":
			return el['id']
	return None

def get_voter_info(election_id, address):

	global api_key

	query = urllib.urlencode({
		'key': api_key,
		'electionId': election_id,
		'address': address
	})

	url = "https://www.googleapis.com/civicinfo/v2/voterinfo?%s" % query

	rsp = requests.get(url)
	return rsp.json()

def election_available(election_id, ocd_ids):
	# TODO: respond according to https://docs.google.com/spreadsheets/d/11XD-WNjtNo3QMrGhDsiZH9qZ4N8RYmfpszJOZ_qH1g8/edit#gid=0
	return True
