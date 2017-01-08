from flask import Flask, render_template, request, redirect, url_for, flash,\
                  jsonify, session, make_response
import random, string, json, httplib2, requests

from oauth2client.client import flow_from_clientsecrets
from oauth2client.client import FlowExchangeError

from db_scheme import Category, Item

G_SECRETS_FILE = 'g_client_secrets.json'
g_client_secrets = json.loads(open(G_SECRETS_FILE, 'r').read())
G_CLIENT_ID = g_client_secrets['web']['client_id']
REDIRECT_URI = 'postmessage'

FB_SECRETS_FILE = 'fb_client_secrets.json'
fb_client_secrets = json.loads(open(FB_SECRETS_FILE, 'r').read())
FB_CLIENT_ID = fb_client_secrets['web']['app_id']

app = Flask(__name__)

def json_result(message, code=401):
    response = make_response(json.dumps(message), code)
    response.headers['Content-Type'] = 'application/json'

    return response

@app.route('/login')
def show_login():
    state = ''.join(random.choice(string.ascii_uppercase + string.digits) for x in xrange(32))
    session['state'] = state

    return render_template('login.html',
                            state_str=state,
                            g_client_id=G_CLIENT_ID,
                            fb_client_id=FB_CLIENT_ID,
                            redirect_uri = REDIRECT_URI)

@app.route('/gconnect', methods=["POST"])
def gconnect():
    if request.args.get('state') != session.get('state'):
        return json_result('Invalid state parameter')

    code = request.data
    try:
        oauth_flow = flow_from_clientsecrets(G_SECRETS_FILE, scope='')
        oauth_flow.redirect_uri = REDIRECT_URI
        credentials = oauth_flow.step2_exchange(code)
    except FlowExchangeError:
        return json_result('Failed to upgrade the authorization code')

    access_token = credentials.access_token
    url = ('https://www.googleapis.com/oauth2/v1/tokeninfo?access_token=%s'
           % access_token)
    h = httplib2.Http()
    result = json.loads(h.request(url, 'GET')[1])
    access_token_error = result.get('error')
    if access_token_error is not None:
        return json_result(access_token_error, 500)

    gplus_id = credentials.id_token['sub']
    if result['user_id'] != gplus_id:
        return json_result("Token's user ID doesn't match given user ID")

    if result['issued_to'] != G_CLIENT_ID:
        return json_result("Token's client ID doesn't match given client ID")

    stored_access_token = session.get('access_token')
    stored_gplus_id = session.get('gplus_id')
    if gplus_id == stored_gplus_id and stored_access_token is not None:
        return json_result('User is already connected', 200)

    session['provider'] = 'google'
    session['access_token'] = access_token
    session['gplus_id'] = gplus_id

    # Get user info
    userinfo_url = "https://www.googleapis.com/oauth2/v1/userinfo"
    params = {'access_token': access_token, 'alt': 'json'}
    answer = requests.get(userinfo_url, params=params)

    data = answer.json()

    session['username'] = data['name']
    session['picture'] = data['picture']
    session['email'] = data['email']

    return 'welcome, ' + session.get('username')

def gdisconnect():
    # only disconnect a connected user
    access_token = session.get('access_token')
    if access_token is None:
        return json_result('Current user is not connected')

    url = ('https://accounts.google.com/o/oauth2/revoke?token=%s'
           %  access_token)
    h = httplib2.Http()
    result = h.request(url, 'GET')[0]

    if(result['status'] == '200'):
        del session['username']
        del session['picture']
        del session['email']
        del session['access_token']
        del session['gplus_id']
        del session['provider']

        return json_result('Successfully disconnected', 200)
    else:
        return json_result('Failed to revoke token for given user', 400)

@app.route('/fbconnect', methods=['POST'])
def fbconnect():
    if request.args.get('state') != session.get('state'):
        return json_result('Invalid state parameter')

    access_token = request.data

    app_secret = fb_client_secrets['web']['app_secret']
    url = 'https://graph.facebook.com/oauth/access_token?grant_type=fb_exchange_token&client_id=%s&client_secret=%s&fb_exchange_token=%s' % (
        FB_CLIENT_ID, app_secret, access_token)
    h = httplib2.Http()
    result = h.request(url, 'GET')[1]

    userinfo_url = "https://graph.facebook.com/v2.4/me"
    # strip expire tag from access token
    token = result.split("&")[0]

    url = 'https://graph.facebook.com/v2.4/me?%s&fields=name,id,email' % token
    h = httplib2.Http()
    result = h.request(url, 'GET')[1]

    data = json.loads(result)

    session['provider'] = 'facebook'
    session['username'] = data['name']
    session['email'] = data['email']
    session['fb_id'] = data['id']

    # Strip out the information before the equals sign in our token
    stored_token = token.split("=")[1]
    session['access_token'] = stored_token

    # Get user picture
    url = 'https://graph.facebook.com/v2.4/me/picture?%s&redirect=0&height=200&width=200' % token
    h = httplib2.Http()
    result = h.request(url, 'GET')[1]
    data = json.loads(result)

    session['picture'] = data["data"]["url"]

    return 'welcome, ' + session.get('username')

def fbdisconnect():
    # Only disconnect a connected user.
    fb_id = session.get('fb_id')
    access_token = session.get('access_token')

    if fb_id is None:
        return json_result('Current user is not connected')

    url = 'https://graph.facebook.com/%s/permissions?access_token=%s' % (fb_id, access_token)
    h = httplib2.Http()
    result = h.request(url, 'DELETE')[1]

    data = json.loads(result)

    if 'success' in data and data['success'] == True:
        del session['username']
        del session['picture']
        del session['email']
        del session['access_token']
        del session['fb_id']
        del session['provider']

        return json_result('Successfully disconnected', 200)
    else:
        return json_result('Failed to revoke token for given user', 400)


@app.route('/disconnect')
def disconnect():
    if 'provider' in session:
        provider = session.get('provider')

        if provider == 'facebook':
            return fbdisconnect()

        elif provider == 'google':
            return gdisconnect()

        else:
            return json_result('Internal error', 500)

    else:
        return json_result('Current user is not connected')

@app.route('/')
def redirect_to_main():
    return redirect(url_for('show_catalog'))

@app.route('/catalog')
def show_catalog():
    categories = Category.get_all()
    return str(len(categories))

@app.route('/catalog/<string:category_label>')
def show_category(category_label):
    return 'some category selected with name ' + category_label

@app.route('/catalog/<string:category_label>/<string:item_label>')
def show_item(category_label, item_label):
    return 'show some item on the page'

@app.route('/catalog/<string:category_label>/add',
           methods=['GET', 'POST'])
def add_item(category_label):
    return 'item creation page'

@app.route('/catalog/<string:category_label>/<string:item_label>/edit',
           methods=['GET', 'POST'])
def edit_item(category_label, item_label):
    return 'edit some item'

@app.route('/catalog/<string:category_label>/<string:item_label>/delete',
           methods=['GET', 'POST'])
def delete_item(category_label, item_label):
    return 'delete some item'


if __name__ == '__main__':
    app.secret_key = 'j9in938j2-fin9348u-r2jefw'
    app.debug = True
    app.run(host='0.0.0.0', port=8080)