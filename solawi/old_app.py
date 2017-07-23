from datetime import datetime
import csv

from flask import render_template, request, redirect, url_for, abort, Response, Blueprint
from flask_login import login_required, login_user, logout_user

from solawi.app import app
from solawi.controller import merge, import_deposits
from solawi.models import Share, Deposit
import solawi.models as models


old_app = Blueprint('old_app', __name__)


@old_app.errorhandler(401)
def unauthorized(_):
    return Response('<p>Login failed</p>'), 401


@old_app.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect("/")

@old_app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        user = models.User.authenticate_and_get(email, password)
        if user:
            login_user(user)
            return redirect(request.args.get("next"))
        else:
            return abort(401)
    else:
        return Response('''
        <form action="" method="post">
            <p><input type=text name=email>
            <p><input type=password name=password>
            <p><input type=submit value=Login>
        </form>
        ''')


@old_app.route("/")
@login_required
def index():
    shares = Share.query.all()
    return render_template("index.html", shares=shares)


@old_app.route("/share/<int:share_id>/rename", methods=["POST"])
@login_required
def rename_share(share_id):
    share = Share.query.get(share_id)
    new_name = request.form.get('name')
    if new_name:
        share.name = new_name
        share.save()
    return redirect(url_for('.share_details', share_id=share_id))


@old_app.route("/share/<int:share_id>")
@login_required
def share_details(share_id):
    share = Share.query.get(share_id)
    all_shares = Share.query.all()
    for a_share in all_shares:
        if a_share.id == share.id:
            all_shares.remove(a_share)
            break

    return render_template("share_details.html",
                           share=share,
                           all_shares=all_shares)


@old_app.route("/deposit/<int:deposit_id>/ignore")
@login_required
def ignore_deposit(deposit_id):
    deposit = Deposit.query.get(deposit_id)
    deposit.ignore = not deposit.ignore
    deposit.save()

    share_for_deposit = deposit.person.share_id
    return redirect(url_for('.share_details', share_id=share_for_deposit))


@old_app.route("/merge_shares", methods=["POST"])
@login_required
def merge_shares():
    original_share_id = request.form.get("original_share")
    merge_share_id = request.form.get("merge_share")
    new_id = merge(original_share_id, merge_share_id)
    if not new_id:
        return redirect(url_for('.index'))
    return redirect(url_for('.share_details', share_id=new_id))


@old_app.route("/person/<int:person_id>")
@login_required
def person_details(person_id):
    person = models.Person.query.get(person_id)
    return render_template("details.html", person=person)


@old_app.route("/bets", methods=["GET", "POST"])
@login_required
def bets_overview():
    if request.method == 'POST':
        all_keys = [k for k in request.form.keys()]
        value_keys = [k for k in all_keys if k.startswith('value')]
        month_keys = [k for k in all_keys if k.startswith('month')]
        station_keys = [k for k in all_keys if k.startswith('station')]

        for share_id in value_keys:
            value = request.form[share_id]
            Share.set_value_for_id(value, share_id.split("-")[1])

        for share_id in station_keys:
            station_id = request.form[share_id]
            if station_id != "None":
                Share.set_station_for_id(station_id, share_id.split("-")[1])

        for share_id in month_keys:
            month = int(request.form[share_id])
            share = Share.query.get(share_id.split("-")[1])
            share.start_date = datetime(2017, month, 1)
            share.save()

        return redirect(url_for('.bets_overview'))
    else:
        shares = Share.query.all()
        stations = models.Station.query.all()
        return render_template("bets.html", shares=shares, stations=stations)


def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1] in ['csv', 'CSV']


@old_app.route('/upload', methods=['GET', 'POST'])
@login_required
def upload_file():
    if request.method == 'POST':
        sent_file = request.files['file']
        if sent_file and allowed_file(sent_file.filename):
            decoded = [a.decode("windows-1252") for a in sent_file.readlines()]
            content = csv.DictReader(decoded, delimiter=";")
            import_deposits([line for line in content])
            return redirect(url_for('.index'))
    return render_template("upload.html")

app.register_blueprint(old_app)