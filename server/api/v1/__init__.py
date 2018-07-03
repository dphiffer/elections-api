__import__('pkg_resources').declare_namespace(__name__)

import flask, json, os, re, sys, arrow
from copy import deepcopy

api = flask.Blueprint('api', __name__)

def get_ocd_ids(areas):
	ocd_ids = []
	for area in areas:
		if area == None:
			continue
		if 'ocd_id' in area:
			ocd_ids.append(area['ocd_id'])
	return ocd_ids

def get_aclu_ids(areas):
	aclu_ids = []
	for area in areas:
		if area == None:
			continue
		if 'aclu_id' in area:
			id = re.search('\d+$', area['aclu_id']).group(0)
			aclu_ids.append(id)
	return '-'.join(aclu_ids)

def format_date(date):
	if date == None:
		return None
	else:
		return arrow.get(date).format('YYYY-MM-DD')

def localize_blurb(office_blurb, race_name):
	for search in office_blurb['alt_names']:
		if re.search(search, race_name):
			blurb = deepcopy(office_blurb)
			replace = office_blurb['alt_names'][search]
			blurb['name'] = blurb['name'].replace(replace, search)
			blurb['title'] = blurb['title'].replace(replace, search)
			blurb['summary'] = blurb['summary'].replace(replace, search)
			blurb['details_title'] = blurb['details_title'].replace(replace, search)
			return blurb
	return office_blurb

def get_elections_by_ocd_ids(ocd_ids, year = '2018'):

	elections = {}

	if len(ocd_ids) == 0:
		return None

	state = re.search('state:(\w\w)', ocd_ids[0]).group(1)

	cur = flask.g.db.cursor()
	cur.execute('''
		SELECT state, online_reg_url, check_reg_url, polling_place_url,
		       voter_id_req, same_day, vote_by_mail, early_voting
		FROM election_info
		WHERE state = %s
	''', (state,))

	row = cur.fetchone()
	if not row:
		return None

	elections = {
		'info': {
			'state': row[0],
			'voter_id_req': row[4],
			'same_day': row[5],
			'vote_by_mail': row[6],
			'early_voting': row[7]
		},
		'links': {
			'online_reg_url': row[1],
			'check_reg_url': row[2],
			'polling_place_url': row[3]
		},
		'calendar': [],
		'ballots': []
	}

	cur.execute('''
		SELECT name, value
		FROM election_dates
		WHERE state = %s
		ORDER BY value
	''', (state,))

	rs = cur.fetchall()

	primary_index = None
	general_index = None

	if rs:
		for row in rs:
			name = row[0]
			date = format_date(row[1])
			if name.startswith('primary_'):
				name = name.replace('primary_', '')
				type = 'primary'
				if primary_index == None:
					primary_index = len(elections['calendar'])
					elections['calendar'].append({
						'type': type,
						'dates': {}
					})
				elections['calendar'][primary_index]['dates'][name] = date
			elif name.startswith('general_'):
				name = name.replace('general_', '')
				type = 'general'
				if general_index == None:
					general_index = len(elections['calendar'])
					elections['calendar'].append({
						'type': type,
						'dates': {}
					})
				elections['calendar'][general_index]['dates'][name] = date

	election_dates = [
		'primary_date',
		'general_date',
		'primary_runoff_date',
		'general_runoff_date'
	]

	ocd_id_list = ', '.join(['%s'] * len(ocd_ids))
	values = tuple(ocd_ids + [year])

	cur.execute('''
		SELECT name, race_type, office_type, office_level,
		       primary_date, primary_runoff_date,
		       general_date, general_runoff_date,
		       ocd_id
		FROM election_races
		WHERE ocd_id IN ({ocd_ids})
		  AND year = %s
	'''.format(ocd_ids=ocd_id_list), values)

	rs = cur.fetchall()
	ballot_lookup = {}
	office_lookup = {}

	offices_template = {
		"federal": [
			{
				"office": "us_senator",
				"blurb": flask.g.blurbs['us_senator'],
				"races": []
			}, {
				"office": "us_representative",
				"blurb": flask.g.blurbs['us_representative'],
				"races": []
			}
		],
		"state": [
			{
				"office": "governor",
				"blurb": flask.g.blurbs['governor'],
				"races": []
			}, {
				"office": "attorney_general",
				"blurb": flask.g.blurbs['attorney_general'],
				"races": []
			}, {
				"office": "secretary_of_state",
				"blurb": flask.g.blurbs['secretary_of_state'],
				"races": []
			}, {
				"office": "state_supreme_court",
				"blurb": flask.g.blurbs['state_supreme_court'],
				"races": []
			}, {
				"office": "state_senator",
				"blurb": flask.g.blurbs['state_senator'],
				"races": []
			}, {
				"office": "state_representative",
				"blurb": flask.g.blurbs['state_representative'],
				"races": []
			}
		],
		"county": [
			{
				"office": "district_attorney",
				"blurb": flask.g.blurbs['district_attorney'],
				"races": []
			}, {
				"office": "county_sheriff",
				"blurb": flask.g.blurbs['county_sheriff'],
				"races": []
			}
		]
	}

	office_lookup_template = {
		'us_senator': 0,
		'us_representative': 1,
		'governor': 0,
		'attorney_general': 1,
		'secretary_of_state': 2,
		'state_supreme_court': 3,
		'state_senator': 4,
		'state_representative': 5,
		'district_attorney': 0,
		'county_sheriff': 1
	}

	if rs:
		for row in rs:

			office_level = row[3]

			election_date_lookup = {
				'primary_date': row[4],
				'general_date': row[6],
				'primary_runoff_date': row[5],
				'general_runoff_date': row[7]
			}

			for name in election_dates:
				if election_date_lookup[name]:

					date = format_date(election_date_lookup[name])

					if name == 'primary_date' or name == 'general_date':
						name = name.replace('_date', '_election_date')

						if not date in ballot_lookup:
							ballot_lookup[date] = len(elections['ballots'])
							elections['ballots'].append({
								'date': date,
								'offices': deepcopy(offices_template),
								'initiatives': []
							})
							office_lookup[date] = deepcopy(office_lookup_template)

						ballot = ballot_lookup[date]

						if not 'type' in elections['ballots'][ballot]:
							type = row[1]
							if type == 'regular':
								type = 'primary' if name == 'primary_election_date' else 'general'
							elif type == 'special':
								type = 'special_primary' if name == 'primary_election_date' else 'special_general'
							elections['ballots'][ballot]['type'] = type

						office = row[2]

						if not office_level in elections['ballots'][ballot]['offices']:
							elections['ballots'][ballot]['offices'][office_level] = []

						if not office in office_lookup[date]:
							office_lookup[date][office] = len(elections['ballots'][ballot]['offices'][office_level])
							elections['ballots'][ballot]['offices'][office_level].append({
								'office': office,
								'races': []
							})

						office_index = office_lookup[date][office]
						elections['ballots'][ballot]['offices'][office_level][office_index]['ocd_id'] = row[8]

						if office_index <= len(elections['ballots'][ballot]['offices'][office_level]) - 1:
							race = {
								'name': row[0]
							}
							for ocd_id in ocd_ids:
								if ocd_id in flask.g.targeted['races']:
									for targeted in flask.g.targeted['races'][ocd_id]:
										if targeted['office'] == office:
											race['targeted'] = [targeted]
							office_obj = elections['ballots'][ballot]['offices'][office_level][office_index]
							office_obj['races'].append(race)

							if 'blurb' in office_obj and 'alt_names' in office_obj['blurb']:
								office_obj['blurb'] = localize_blurb(office_obj['blurb'], race['name'])
						else:
							print("Warning: could not add %s to %s office %d" % (row[0], office_level, office_index))

					if name.startswith('primary_'):
						name = name.replace('primary_', '')
						if not name in elections['calendar'][primary_index]['dates']:
							elections['calendar'][primary_index]['dates'][name] = date
					elif name.startswith('general_'):
						name = name.replace('general_', '')
						if not name in elections['calendar'][general_index]['dates']:
							elections['calendar'][general_index]['dates'][name] = date

	def filter_offices(office):
		return len(office['races']) > 0

	for ballot in elections['ballots']:
		for office_level in ballot['offices']:
			ballot['offices'][office_level] = filter(filter_offices, ballot['offices'][office_level])

	def sort_ballots(a, b):
		return 1 if a['date'] > b['date'] else -1
	elections['ballots'].sort(cmp=sort_ballots)

	def sort_calendar(a, b):
		return 1 if a['dates']['election_date'] > b['dates']['election_date'] else -1
	elections['calendar'].sort(cmp=sort_calendar)

	for ocd_id in ocd_ids:
		if ocd_id in flask.g.targeted['initiatives']:
			for ballot in elections['ballots']:
				ballot['initiatives'] = flask.g.targeted['initiatives'][ocd_id]

	return elections

def get_state_by_coords(lat, lng):

	include_geometry = flask.request.args.get('geometry', False)

	columns = "aclu_id, geoid, ocd_id, name, state, area_land, area_water"

	if include_geometry == '1':
		columns += ', boundary_simple'

	cur = flask.g.db.cursor()
	cur.execute('''
		SELECT {columns}
		FROM states
		WHERE ST_within(ST_GeomFromText('POINT({lng} {lat})', 4326), boundary_geom)
	'''.format(columns=columns, lng=lng, lat=lat))

	rs = cur.fetchall()
	state = None

	if rs:
		for row in rs:
			state = {
				'aclu_id': row[0],
				'geoid': row[1],
				'ocd_id': row[2],
				'name': row[3],
				'state': row[4],
				'area_land': row[5],
				'area_water': row[6]
			}

			if include_geometry == '1':
				state['geometry'] = row[7]

	cur.close()
	return state

def get_state_by_abbrev(abbrev):

	include_geometry = flask.request.args.get('geometry', False)

	columns = "aclu_id, geoid, ocd_id, name, state, area_land, area_water"

	if include_geometry == '1':
		columns += ', boundary_simple'

	cur = flask.g.db.cursor()
	cur.execute('''
		SELECT {columns}
		FROM states
		WHERE state = %s
	'''.format(columns=columns), (abbrev,))

	rs = cur.fetchall()
	state = None

	if rs:
		for row in rs:
			state = {
				'aclu_id': row[0],
				'geoid': row[1],
				'ocd_id': row[2],
				'name': row[3],
				'state': row[4],
				'area_land': row[5],
				'area_water': row[6]
			}

			if include_geometry == '1':
				state['geometry'] = row[7]

	cur.close()
	return state

def get_district_by_coords(lat, lng, session_num=115):

	include_geometry = flask.request.args.get('geometry', False)

	columns = 'aclu_id, geoid, ocd_id, name, start_session, end_session, state, district_num, area'

	if include_geometry == '1':
		columns += ', boundary_simple'

	cur = flask.g.db.cursor()
	cur.execute('''
		SELECT {columns}
		FROM congress_districts
		WHERE ST_within(ST_GeomFromText('POINT({lng} {lat})', 4326), boundary_geom)
		  AND (district_num > 0 OR at_large_only = 'Y')
		  AND start_session <= %s
		  AND end_session >= %s
	'''.format(columns=columns, lng=lng, lat=lat), (session_num, session_num))

	rs = cur.fetchall()
	district = None

	if rs:
		for row in rs:

			aclu_id = row[0]
			geoid = row[1]
			ocd_id = row[2]
			name = row[3]
			start_session = row[4]
			end_session = row[5]
			state = row[6]
			district_num = row[7]
			area = row[8]

			at_large = (district_num == 0)
			non_voting = (district_num == 98)

			district = {
				'aclu_id': aclu_id,
				'geoid': geoid,
				'ocd_id': ocd_id,
				'name': name,
				'start_session': start_session,
				'end_session': end_session,
				'start_date': flask.g.sessions[start_session]['start_date'],
				'end_date': flask.g.sessions[end_session]['end_date'],
				'state': state,
				'district_num': district_num,
				'area': area,
				'at_large': at_large,
				'non_voting': non_voting
			}

			if include_geometry == '1':
				district['geometry'] = row[9]

	cur.close()
	return district

def get_district_by_id(aclu_id):

	include_geometry = flask.request.args.get('geometry', False)

	columns = 'aclu_id, geoid, ocd_id, name, start_session, end_session, state, district_num, area'

	if include_geometry == '1':
		columns += ', boundary_simple'

	cur = flask.g.db.cursor()
	cur.execute('''
		SELECT {columns}
		FROM congress_districts
		WHERE aclu_id = %s
	'''.format(columns=columns), (aclu_id,))

	rs = cur.fetchall()
	district = None

	if rs:
		for row in rs:

			aclu_id = row[0]
			geoid = row[1]
			ocd_id = row[2]
			name = row[3]
			start_session = row[4]
			end_session = row[5]
			state = row[6]
			district_num = row[7]
			area = row[8]

			at_large = (district_num == 0)
			non_voting = (district_num == 98)

			district = {
				'aclu_id': aclu_id,
				'geoid': geoid,
				'ocd_id': ocd_id,
				'name': name,
				'start_session': start_session,
				'end_session': end_session,
				'start_date': flask.g.sessions[start_session]['start_date'],
				'end_date': flask.g.sessions[end_session]['end_date'],
				'state': state,
				'district_num': district_num,
				'area': area,
				'at_large': at_large,
				'non_voting': non_voting
			}

			if include_geometry == '1':
				district['geometry'] = row[9]

	cur.close()
	return district

def get_county_by_coords(lat, lng):

	include_geometry = flask.request.args.get('geometry', False)

	columns = 'aclu_id, geoid, ocd_id, name, state, area_land, area_water'

	if include_geometry == '1':
		columns += ', boundary_simple'

	cur = flask.g.db.cursor()
	cur.execute('''
		SELECT {columns}
		FROM counties
		WHERE ST_within(ST_GeomFromText('POINT({lng} {lat})', 4326), boundary_geom)
	'''.format(columns=columns, lng=lng, lat=lat))

	rs = cur.fetchall()
	county = None

	if rs:
		for row in rs:

			county = {
				'aclu_id': row[0],
				'geoid': row[1],
				'ocd_id': row[2],
				'name': row[3],
				'state': row[4],
				'area_land': row[5],
				'area_water': row[6]
			}

			if include_geometry == '1':
				county['geometry'] = row[7]

	cur.close()
	return county

def get_county_by_id(aclu_id):

	include_geometry = flask.request.args.get('geometry', False)

	columns = 'aclu_id, geoid, ocd_id, name, state, area_land, area_water'

	if include_geometry == '1':
		columns += ', boundary_simple'

	cur = flask.g.db.cursor()
	cur.execute('''
		SELECT {columns}
		FROM counties
		WHERE aclu_id = %s
	'''.format(columns=columns), (aclu_id,))

	rs = cur.fetchall()
	county = None

	if rs:
		for row in rs:

			county = {
				'aclu_id': row[0],
				'geoid': row[1],
				'ocd_id': row[2],
				'name': row[3],
				'state': row[4],
				'area_land': row[5],
				'area_water': row[6]
			}

			if include_geometry == '1':
				county['geometry'] = row[7]

	cur.close()
	return county

def get_state_legs_by_coords(lat, lng):

	include_geometry = flask.request.args.get('geometry', False)

	columns = 'aclu_id, geoid, ocd_id, name, state, chamber, district_num, area_land, area_water'

	if include_geometry == '1':
		columns += ', boundary_simple'

	cur = flask.g.db.cursor()
	cur.execute('''
		SELECT {columns}
		FROM state_leg
		WHERE ST_within(ST_GeomFromText('POINT({lng} {lat})', 4326), boundary_geom)
	'''.format(columns=columns, lng=lng, lat=lat))

	rs = cur.fetchall()
	state_legs = []

	if rs:
		for row in rs:

			state_leg = {
				'aclu_id': row[0],
				'geoid': row[1],
				'ocd_id': row[2],
				'name': row[3],
				'state': row[4],
				'chamber': row[5],
				'district_num': row[6],
				'area_land': row[7],
				'area_water': row[8]
			}

			if include_geometry == '1':
				state_leg['geometry'] = row[9]

			state_legs.append(state_leg)

	cur.close()
	return state_legs

def get_state_legs_by_ids(aclu_ids):

	include_geometry = flask.request.args.get('geometry', False)

	columns = 'aclu_id, geoid, ocd_id, name, state, chamber, district_num, area_land, area_water'

	if include_geometry == '1':
		columns += ', boundary_simple'

	aclu_id_list = ', '.join(['%s'] * len(aclu_ids))
	aclu_id_values = tuple(aclu_ids)

	cur = flask.g.db.cursor()
	cur.execute('''
		SELECT {columns}
		FROM state_leg
		WHERE aclu_id IN ({aclu_ids})
	'''.format(columns=columns, aclu_ids=aclu_id_list), aclu_id_values)

	rs = cur.fetchall()
	state_legs = []

	if rs:
		for row in rs:

			state_leg = {
				'aclu_id': row[0],
				'geoid': row[1],
				'ocd_id': row[2],
				'name': row[3],
				'state': row[4],
				'chamber': row[5],
				'district_num': row[6],
				'area_land': row[7],
				'area_water': row[8]
			}

			if include_geometry == '1':
				state_leg['geometry'] = row[9]

			state_legs.append(state_leg)

	cur.close()
	return state_legs

def get_legislators_by_state(state, session_num=115):

	session = flask.g.sessions[session_num]

	cur = flask.g.db.cursor()
	cur.execute('''
		SELECT id, aclu_id, start_date, end_date, type, state, district_num, party
		FROM congress_legislator_terms
		WHERE end_date >= CURRENT_DATE
		  AND state = %s
		  AND type = 'sen'
		ORDER BY end_date DESC
	''', (state,))

	return get_legislators(cur)

def get_legislators_by_district(state, district_num, session_num=115):

	cur = flask.g.db.cursor()
	cur.execute('''
		SELECT id, aclu_id, start_date, end_date, type, state, district_num, party
		FROM congress_legislator_terms
		WHERE end_date >= CURRENT_DATE
		  AND state = %s
		  AND (
			district_num IS NULL OR
			district_num = %s
		  )
		ORDER BY end_date DESC
	''', (state, district_num))

	return get_legislators(cur)

def get_legislators(cur):

	legislators = {}
	aclu_ids = []
	term_ids = []

	rs = cur.fetchall()
	if rs:
		for row in rs:
			aclu_id = row[1]
			office = 'us_representative' if row[4] == 'rep' else 'us_senator'
			legislators[aclu_id] = {
				'term': {
					'start_date': arrow.get(row[2]).format('YYYY-MM-DD'),
					'end_date': arrow.get(row[3]).format('YYYY-MM-DD'),
					'office': office,
					'state': row[5],
					'party': row[7]
				}
			}
			if row[4] == 'rep':
				legislators[aclu_id]['term']['district_num'] = row[6]
			aclu_ids.append(aclu_id)
			term_ids.append(str(row[0]))

	if len(aclu_ids) == 0:
		return {}

	aclu_id_list = ', '.join(['%s'] * len(aclu_ids))
	aclu_id_values = tuple(aclu_ids)

	cur.execute('''
		SELECT aclu_id, first_name, last_name, full_name, birthday, gender
		FROM congress_legislators
		WHERE aclu_id IN ({aclu_ids})
	'''.format(aclu_ids=aclu_id_list), aclu_id_values)

	rs = cur.fetchall()
	if rs:
		for row in rs:
			aclu_id = row[0]
			legislators[aclu_id]['name'] = {
				'first_name': row[1],
				'last_name': row[2],
				'full_name': row[3]
			}
			legislators[aclu_id]['bio'] = {
				'birthday': arrow.get(row[4]).format('YYYY-MM-DD'),
				'gender': row[5]
			}

	cur.execute('''
		SELECT aclu_id, display_name, running_in_2018
		FROM congress_legislator_details
		WHERE aclu_id IN ({aclu_ids})
	'''.format(aclu_ids=aclu_id_list), aclu_id_values)

	rs = cur.fetchall()
	if rs:
		for row in rs:
			aclu_id = row[0]
			legislators[aclu_id]['name']['display_name'] = row[1]
			legislators[aclu_id]['running_in_2018'] = True if row[2] else False

	term_id_list = ', '.join(['%s'] * len(term_ids))
	term_id_values = tuple(term_ids)
	cur.execute('''
		SELECT aclu_id, detail_name, detail_value
		FROM congress_legislator_term_details
		WHERE term_id IN ({term_ids})
	'''.format(term_ids=term_id_list), term_id_values)

	rs = cur.fetchall()
	if rs:
		for row in rs:
			aclu_id = row[0]
			key = row[1]
			value = row[2]
			if key == 'class':
				legislators[aclu_id]['term'][key] = int(value)
			elif key == 'state_rank':
				legislators[aclu_id]['term'][key] = value
			else:
				if not 'contact' in legislators[aclu_id]:
					legislators[aclu_id]['contact'] = {}
				legislators[aclu_id]['contact'][key] = value

	cur.execute('''
		SELECT aclu_id, concordance_name, concordance_value
		FROM congress_legislator_concordances
		WHERE aclu_id IN ({aclu_ids})
	'''.format(aclu_ids=aclu_id_list), aclu_id_values)

	rs = cur.fetchall()
	if rs:
		for row in rs:
			aclu_id = row[0]
			key = row[1]
			value = row[2]
			if not 'id' in legislators[aclu_id]:
				legislators[aclu_id]['id'] = {}
			legislators[aclu_id]['id'][key] = value
			if key == 'bioguide':
				path = 'congress_photos/%s.jpg' % value
				abs_path = '/usr/local/aclu/elections-api/data/%s' % path
				if os.path.isfile(abs_path):
					url_root = flask.request.url_root
					if re.search('elb\.amazonaws\.com', url_root):
						url_root = 'https://elections.api.aclu.org/'
					elif url_root == 'http://elections.api.aclu.org/':
						url_root = 'https://elections.api.aclu.org/'
					legislators[aclu_id]['photo'] = "%s%s" % (url_root, path)

	cur.execute('''
		SELECT aclu_id, social_media_name, social_media_value
		FROM congress_legislator_social_media
		WHERE aclu_id IN ({aclu_ids})
	'''.format(aclu_ids=aclu_id_list), aclu_id_values)

	rs = cur.fetchall()
	if rs:
		for row in rs:
			aclu_id = row[0]
			key = row[1]
			value = row[2]
			if not 'social' in legislators[aclu_id]:
				legislators[aclu_id]['social'] = {}
			legislators[aclu_id]['social'][key] = value

	score_filter = flask.request.args.get('scores', 'voted')

	cur.execute('''
		SELECT aclu_id, legislator_id, position, name, value
		FROM congress_legislator_scores
		WHERE legislator_id IN ({aclu_ids})
	'''.format(aclu_ids=aclu_id_list), aclu_id_values)

	rs = cur.fetchall()
	if rs:
		for row in rs:
			aclu_id = row[0]
			legislator_id = row[1]
			position = row[2]
			name = row[3]
			value = row[4]

			if not 'scores' in legislators[legislator_id]:
				legislators[legislator_id]['scores'] = []

			if name == 'total':
				legislators[legislator_id]['total_score'] = value
			else:
				score = {
					'aclu_id': aclu_id,
					'aclu_position': position,
					'name': name,
					'status': 'unknown'
				}
				if value == '1' or value == '0':
					score['vote'] = True if value == '1' else False
					score['status'] = 'voted'
				elif value == 'Missed':
					score['status'] = 'missed'
				elif value == 'Not yet in office':
					score['status'] = 'not_in_office'
				elif value == 'Not on committee':
					score['status'] = 'not_on_committee'

				if score_filter == 'all' or score_filter == score['status']:
					legislators[legislator_id]['scores'].append(score)

	cur.close()

	legislator_list = []
	for aclu_id in legislators:
		legislator_list.append(legislators[aclu_id])

	def sort_legislators(a, b):
		if a['term']['office'] == 'us_senator' and b['term']['office'] == 'us_senator':
			if a['term']['class'] > b['term']['class']:
				return -1
			elif a['term']['class'] < b['term']['class']:
				return 1
		elif a['term']['office'] == 'us_senator' and b['term']['office'] == 'us_representative':
			return -1
		elif a['term']['office'] == 'us_representative' and b['term']['office'] == 'us_senator':
			return 1

		if a['name']['last_name'] < b['name']['last_name']:
			return -1
		elif a['name']['last_name'] > b['name']['last_name']:
			return 1
		else:
			return 0

	legislator_list.sort(cmp=sort_legislators)

	return legislator_list

def get_spatial_request():

	lat = flask.request.args.get('lat', None)
	lng = flask.request.args.get('lng', None)
	id = flask.request.args.get('id', None)

	if (lat == None or lng == None) and id == None:
		return "Please include either 'lat' and 'lng' args or an 'id' arg."

	if lat != None and lng != None:

		if not re.search('^-?\d+(\.\d+)?', lat):
			return "Please include a numeric 'lat'."

		if not re.search('^-?\d+(\.\d+)?', lng):
			return "Please include a numeric 'lng'."

		return {
			'lat': lat,
			'lng': lng
		}

	elif re.search('^(\d+)(-\d+)*$', id):

		id_list = map(int, id.split('-'))

		placeholders = ', '.join(['%s'] * len(id_list))
		values = tuple(id_list)

		cur = flask.g.db.cursor()
		cur.execute('''
			SELECT aclu_id, type
			FROM aclu_ids
			WHERE id IN ({id_list})
		'''.format(id_list=placeholders), values)

		rsp = {}
		rs = cur.fetchall()
		if rs:
			for row in rs:
				type = row[1]
				aclu_id = row[0]
				if type == 'state_leg':
					if not 'state_leg' in rsp:
						rsp['state_leg'] = []
					rsp['state_leg'].append(aclu_id)
				else:
					rsp[type] = aclu_id

		return rsp

	else:
		return 'Could not understand spatial request.'

def get_congress_by_coords(lat, lng):

	district = get_district_by_coords(lat, lng)

	if not district:
		rsp = {
			'ok': False,
			'error': 'No congressional district found.'
		}
	else:
		legislators = get_legislators_by_district(district["state"], district["district_num"])
		rsp = {
			'ok': True,
			'district': district,
			'legislators': legislators
		}

	return rsp

def get_congress_by_id(aclu_id):

	district = get_district_by_id(aclu_id)

	if not district:
		rsp = {
			'ok': False,
			'error': 'No congressional district found.'
		}
	else:
		legislators = get_legislators_by_district(district["state"], district["district_num"])
		rsp = {
			'ok': True,
			'district': district,
			'legislators': legislators
		}

	return rsp

@api.route("/")
def index():
	return flask.jsonify({
		'ok': False,
		'error': 'Please pick a valid endpoint.',
		'valid_endpoints': {
			'/v1/pip': {
				'description': 'Point in polygon election lookup by location.',
				'args': {
					'lat': 'Latitude',
					'lng': 'Longitude',
					'id': 'Hyphen-separated list of numeric IDs (alternative to lat/lng)',
					'scores': 'Congress legislator score filter (optional; scores=all)',
					'geometry': 'Include GeoJSON geometries with districts (optional; geometry=1)'
				}
			},
			'/v1/state': {
				'description': 'State election lookup by location.',
				'args': {
					'lat': 'Latitude',
					'lng': 'Longitude',
					'geometry': 'Include GeoJSON geometries with districts (optional; geometry=1)'
				}
			},
			'/v1/congress': {
				'description': 'Congress election lookup by location.',
				'args': {
					'lat': 'Latitude',
					'lng': 'Longitude',
					'scores': 'Congress legislator score filter (optional; scores=all)',
					'geometry': 'Include GeoJSON geometries with districts (optional; geometry=1)'
				}
			},
			'/v1/congress/district': {
				'description': 'Congressional district lookup by location.',
				'args': {
					'lat': 'Latitude',
					'lng': 'Longitude',
					'geometry': 'Include GeoJSON geometries with districts (optional; geometry=1)'
				}
			},
			'/v1/congress/scores': {
				'description': 'Index of congressional legislator scores.',
				'args': {}
			},
			'/v1/county': {
				'description': 'County election lookup by location.',
				'args': {
					'lat': 'Latitude',
					'lng': 'Longitude',
					'geometry': 'Include GeoJSON geometries with districts (optional; geometry=1)'
				}
			},
			'/v1/state_leg': {
				'description': 'State legislature election lookup by location.',
				'args': {
					'lat': 'Latitude',
					'lng': 'Longitude',
					'geometry': 'Include GeoJSON geometries with districts (optional; geometry=1)'
				}
			},
			'/v1/blurbs': {
				'description': 'Descriptive blurbs about various elected positions.',
				'args': {}
			}
		}
	})

@api.route("/pip")
def pip():
	req = get_spatial_request()
	if type(req) == str:
		return flask.jsonify({
			'ok': False,
			'error': req
		})

	if 'lat' in req and 'lng' in req:
		lat = req['lat']
		lng = req['lng']

		congress = get_congress_by_coords(lat, lng)
		if (congress["ok"]):
			del congress["ok"]

		state = get_state_by_abbrev(congress['district']['state'])
		county = get_county_by_coords(lat, lng)
		state_legs = get_state_legs_by_coords(lat, lng)

	else:
		congress = get_congress_by_id(req['congress_district'])
		if (congress["ok"]):
			del congress["ok"]

		state = get_state_by_abbrev(congress['district']['state'])
		county = get_county_by_id(req['county'])
		state_legs = get_state_legs_by_ids(req['state_leg'])

	areas = [state, congress['district'], county] + state_legs
	ocd_ids = get_ocd_ids(areas)
	aclu_ids = get_aclu_ids(areas)
	elections = get_elections_by_ocd_ids(ocd_ids)

	rsp = {
		'ok': True,
		'id': aclu_ids,
		'elections': elections,
		'state': state,
		'congress': congress,
		'county': county,
		'state_leg': state_legs
	}

	include_geometry = flask.request.args.get('geometry', False)
	if include_geometry == '1':
		rsp['geometry'] = {
			state['ocd_id']: {
				'name': state['name'],
				'geometry': state['geometry']
			},
			congress['district']['ocd_id']: {
				'name': congress['district']['name'],
				'geometry': congress['district']['geometry']
			},
			county['ocd_id']: {
				'name': county['name'],
				'geometry': county['geometry']
			}
		}
		del state['geometry']
		del congress['district']['geometry']
		del county['geometry']
		for leg in state_legs:
			ocd_id = leg['ocd_id']
			rsp['geometry'][ocd_id] = {
				'name': leg['name'],
				'geometry': leg['geometry']
			}
			del leg['geometry']

	return flask.jsonify(rsp)

@api.route("/state")
def state():
	req = get_spatial_request()

	if type(req) == str:
		return flask.jsonify({
			'ok': False,
			'error': req
		})

	lat = req['lat']
	lng = req['lng']

	rsp = get_state_by_coords(lat, lng)
	if rsp == None:
		return flask.jsonify({
			'ok': False,
			'error': 'No state found.'
		})

	legislators = get_legislators_by_state(rsp['state'])

	return flask.jsonify({
		'ok': True,
		'state': rsp,
		'congress': {
			'legislators': legislators
		}
	})

@api.route("/congress")
def congress():
	req = get_spatial_request()
	if type(req) == str:
		return flask.jsonify({
			'ok': False,
			'error': req
		})

	lat = req['lat']
	lng = req['lng']

	rsp = get_congress_by_coords(lat, lng)
	return flask.jsonify({
		'ok': True,
		'congress': rsp
	})

@api.route("/congress/district")
def congress_district():
	req = get_spatial_request()

	if type(req) == str:
		return flask.jsonify({
			'ok': False,
			'error': req
		})

	lat = req['lat']
	lng = req['lng']

	district = get_district_by_coords(lat, lng)

	return flask.jsonify({
		'ok': True,
		'district': district
	})

@api.route("/congress/scores")
def congress_scores():

	cur = flask.g.db.cursor()
	cur.execute('''
		SELECT aclu_id, vote_context, roll_call, vote_date, vote_type, bill,
		       amendment, title, description, committee, link
		FROM congress_legislator_score_index
		ORDER BY aclu_id
	''')

	scores = []

	rs = cur.fetchall()
	if rs:
		for row in rs:
			scores.append({
				'aclu_id': row[0],
				'vote_context': row[1],
				'roll_call': row[2],
				'vote_date': arrow.get(row[3]).format('YYYY-MM-DD'),
				'vote_type': row[4],
				'bill': row[5],
				'amendment': row[6],
				'title': row[7],
				'description': row[8],
				'committee': row[9],
				'link': row[10]
			})

	return flask.jsonify({
		'ok': True,
		'congress_scores': scores
	})

@api.route("/county")
def pip_county():
	req = get_spatial_request()

	if type(req) == str:
		return flask.jsonify({
			'ok': False,
			'error': req
		})

	lat = req['lat']
	lng = req['lng']

	rsp = get_county_by_coords(lat, lng)
	if rsp == None:
		return flask.jsonify({
			'ok': False,
			'error': 'No county found.'
		})

	return flask.jsonify({
		'ok': True,
		'county': rsp
	})

@api.route("/state_leg")
def pip_state_leg():
	req = get_spatial_request()

	if type(req) == str:
		return flask.jsonify({
			'ok': False,
			'error': req
		})

	lat = req['lat']
	lng = req['lng']

	rsp = get_state_legs_by_coords(lat, lng)
	if len(rsp) == 0:
		return flask.jsonify({
			'ok': False,
			'error': 'No state legislation found.'
		})

	return flask.jsonify({
		'ok': True,
		'state_leg': rsp
	})

@api.route("/blurbs")
def blurbs():

	cur = flask.g.db.cursor()
	cur.execute('''
		SELECT position, description
		FROM election_blurbs
		ORDER BY position
	''')

	blurbs = []

	rs = cur.fetchall()
	if rs:
		for row in rs:
			blurbs.append({
				'position': row[0],
				'description': row[1]
			})

	return flask.jsonify({
		'ok': True,
		'blurbs': blurbs
	})
