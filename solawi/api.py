from datetime import date
from decimal import Decimal
from functools import wraps
from http import HTTPStatus
from typing import Optional

from flask import Blueprint, abort, current_app, jsonify, request
from flask_jwt_extended import create_access_token, get_jwt_identity, verify_jwt_in_request
from flask_pydantic import validate
from pydantic import Extra
from pydantic.main import BaseModel
from pydantic.types import constr
from sqlalchemy.orm import joinedload

from solawi import models
from solawi.app import app, db
from solawi.controller import merge
from solawi.models import Bet, Deposit, Member, Person, Share, User

api = Blueprint("api", __name__)


def login_required():
    def wrapper(fn):
        @wraps(fn)
        def decorator(*args, **kwargs):
            verify_jwt_in_request()
            current_user = User.query.filter(User.email == get_jwt_identity()).one()
            if not current_user.password_changed_at:
                return abort(403)
            return current_app.ensure_sync(fn)(*args, **kwargs)

        return decorator

    return wrapper


class LoginSchema(BaseModel):
    email: str
    password: str


@api.route("/login", methods=["POST"])
@validate()
def api_login(body: LoginSchema):
    email = body.email
    password = body.password
    user = models.User.authenticate_and_get(email, password)
    if user:
        access_token = create_access_token(identity=email)
        return jsonify(access_token=access_token, id=user.id), 200
    else:
        return jsonify({"message": "login failed"}), 401


@api.route("/shares")
@login_required()
def shares_list():
    shares = Share.query.options(joinedload(Share.bets)).options(joinedload(Share.members)).all()
    shares = [share.json for share in shares]
    return jsonify(shares=shares)


@api.route("/shares/<int:share_id>/emails")
@login_required()
def share_email_list(share_id: int):
    share = Share.get(share_id)
    return jsonify(emails=[member.email for member in share.members])


@api.route("/members", methods=["GET"])
@login_required()
def member_list():
    members = db.session.query(Member).options(joinedload(Member.share)).all()
    result = []

    if request.args.get("active"):
        members = [member for member in members if member.share.currently_active]

    for member in members:
        json = member.json
        json["station_name"] = member.share.station_name if member.share else ""
        json["join_date"] = member.share.join_date if member.share else ""
        result.append(json)
    return jsonify(members=result)


class MemberSchema(BaseModel, extra=Extra.forbid):
    name: str
    share_id: Optional[int]
    email: Optional[str]
    phone: Optional[str]


@api.route("/members", methods=["POST"])
@login_required()
@validate()
def post_member(body: MemberSchema):
    share_id = body.share_id
    if not share_id:
        share = Share()
        share.save()
        share_id = share.id
    member = Member(name=body.name, email=body.email, phone=body.phone, share_id=share_id)
    member.save()
    return jsonify(member=member.json)


class MemberPatchSchema(MemberSchema):
    name: Optional[str]


@api.route("/members/<int:member_id>", methods=["PATCH"])
@login_required()
@validate()
def patch_member(body: MemberPatchSchema, member_id: int):
    member = Member.get(member_id)
    json = body.dict()
    for key, value in json.items():
        if value is not None:
            setattr(member, key, value)
    member.save()
    return jsonify(member=member.json)


@api.route("/members/<int:member_id>", methods=["DELETE"])
@login_required()
def member_delete(member_id: int):
    member = Member.get(member_id)
    member.delete()
    return "", HTTPStatus.NO_CONTENT


@api.route("/shares/payment_status", methods=["GET"])
@login_required()
def get_payment_list():
    deposit_map = Share.get_deposit_map()
    expected_amount_map = Share.get_expected_amount_map()
    shares = (
        db.session.query(Share)
        .options(joinedload(Share.members))
        .options(joinedload(Share.station))
        .all()
    )
    res = []
    for share in shares:
        deposit_details = deposit_map.get(share.id, {})
        share_payments = {
            "id": share.id,
            "name": share.name,
            "total_deposits": deposit_details.get("total_deposits", 0),
            "number_of_deposits": deposit_details.get("number_of_deposits", 0),
            "archived": share.archived,
            "note": share.note,
            "station_name": share.station.name if share.station else "",
            "expected_today": expected_amount_map.get(share.id, 0),
        }
        share_payments["difference_today"] = (
            share_payments["total_deposits"] - share_payments["expected_today"]
        )
        res.append(share_payments)
    return jsonify(shares=res)


@api.route("/stations")
@login_required()
def get_stations():
    stations = [station.json for station in models.Station.query.all()]
    return jsonify(stations=stations)


@api.route("/shares/<int:share_id>", methods=["GET"])
@login_required()
def shares_details(share_id: int):
    share = Share.get(share_id)
    dict_share = share.json
    dict_share["expected_today"] = share.expected_today
    dict_share["total_deposits"] = share.total_deposits or 0
    dict_share["difference_today"] = -(
        Decimal(dict_share["expected_today"]) - dict_share["total_deposits"]
    )
    return jsonify(share=dict_share)


@api.route("/shares/<int:share_id>/deposits", methods=["GET"])
@login_required()
def share_deposits(share_id: int):
    deposits = Share.get_deposits(share_id)
    return jsonify(deposits=deposits)


@api.route("/shares/<int:share_id>/bets", methods=["GET"])
@login_required()
def share_bets(share_id: int):
    bets = Share.get_bets(share_id)
    return jsonify(bets=bets)


class BetSchema(BaseModel, extra=Extra.forbid):
    value: Decimal
    start_date: date
    end_date: Optional[date]


@api.route("/shares/<int:share_id>/bets", methods=["POST"])
@validate()
@login_required()
def post_bet(body: BetSchema, share_id: int):
    bet = Bet(share_id=share_id, **body.dict())
    bet.save()
    return jsonify(bet=bet.json)


@api.route("/bets/<int:bet_id>", methods=["PUT"])
@validate()
@login_required()
def put_bet(body: BetSchema, bet_id: int):
    bet = Bet.query.get_or_404(bet_id)
    json = body.dict()

    for key, value in json.items():
        setattr(bet, key, value)
    bet.save()

    return jsonify(bet=bet.json)


@api.route("/shares/<int:share_id>/bets/<int:bet_id>", methods=["DELETE"])
@login_required()
def delete_bet(share_id: int, bet_id: int):
    bet = Bet.query.get_or_404(bet_id)
    bet.delete()
    return jsonify(), 204


class SharePatchSchema(BaseModel, extra=Extra.forbid):
    note: Optional[str]
    archived: Optional[bool]


@api.patch("/shares/<int:share_id>")
@login_required()
@validate()
def patch_share(body: SharePatchSchema, share_id: int):
    share = Share.get(share_id)
    for key, value in body.dict().items():
        setattr(share, key, value)
    share.save()
    resp = share.json
    return jsonify(share=resp)


class ShareSchema(BaseModel):
    id: str
    station_id: int
    note: Optional[str]
    archived: Optional[bool]


@api.route("/shares/<int:share_id>", methods=["POST"])
@login_required()
@validate()
def post_shares_details(body: ShareSchema, share_id: int):
    share = Share.get(share_id)
    json = body.dict()
    for field in ["station_id", "note", "archived"]:
        if field in json:
            setattr(share, field, json.get(field))
    share.save()
    resp = share.json
    return jsonify(share=resp)


@api.route("/shares", methods=["POST"])
@login_required()
def add_share():
    json = request.get_json()
    share = Share()
    for field in json:
        setattr(share, field, json.get(field))
    share.save()
    return jsonify(share=share.json), 201


class DepositPatchSchema(BaseModel, extra=Extra.forbid):
    ignore: Optional[bool]
    is_security: Optional[bool]


@api.patch("/deposits/<int:deposit_id>")
@login_required()
@validate()
def patch_deposit(body: DepositPatchSchema, deposit_id: int):
    deposit = Deposit.get(deposit_id)
    json = body.dict()
    for field in json:
        setattr(deposit, field, json.get(field))
    deposit.save()
    return jsonify(deposit=deposit.json)


class DepositSchema(DepositPatchSchema):
    amount: str
    timestamp: str
    title: str
    person_id: int


@api.post("/deposits/")
@login_required()
@validate()
def post_deposit(body: DepositSchema):
    current_user_email = get_jwt_identity()
    current_user = User.query.filter(User.email == current_user_email).one()
    deposit = Deposit(added_by=current_user.id)
    json = body.dict()
    for field in json:
        setattr(deposit, field, json.get(field))
    deposit.save()
    return jsonify(deposit=deposit.json)


class MergeSharesSchema(BaseModel):
    share1: int
    share2: int


@api.route("/shares/merge", methods=["POST"])
@login_required()
@validate()
def merge_shares(body: MergeSharesSchema):
    merge(body.share1, body.share2)
    return jsonify(message="success")


@api.route("/person/<int:person_id>", methods=["GET"])
@login_required()
def get_person(person_id: int):
    return jsonify(Person.get(person_id).json)


@api.route("/users", methods=["GET"])
@login_required()
def user_list():
    users = User.get_all_emails()
    return jsonify(users=users)


class PatchUserModel(BaseModel):
    password: constr(min_length=14)


@api.route("/users/<int:id>", methods=["PATCH"])
@login_required()
@validate()
def modify_user(body: PatchUserModel, id: int):
    user = User.get(id)
    current_user_email = get_jwt_identity()
    if not user or not user.email == current_user_email:
        return jsonify({"message": "you cannot change another users's password"}), 403
    user.password = body.password
    user.save()
    return jsonify(user=user.json)


app.register_blueprint(api, url_prefix="/api/v1")
