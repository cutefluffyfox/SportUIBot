import dill as pickle
from requests.sessions import Session, session
import firebase_admin
from firebase_admin import db
from os import getenv
from collections import OrderedDict
import dotenv

dotenv.load_dotenv(dotenv.find_dotenv())
cred_obj = firebase_admin.credentials.Certificate('firebase-adminsdk.json')
default_app = firebase_admin.initialize_app(
    cred_obj,
    {
        'databaseURL': getenv('DATABASE_URL')
    }
)


def create_session(user_id: int) -> Session or None:
    s = session()
    data = get_user(user_id)
    if data:
        data: OrderedDict
        s.cookies['sessionid'] = data['session_id']
        s.cookies['csrftoken'] = data['csrf_token']
        s.cookies['student_id'] = data['student_id']
        return s
    return None


def create_user(user_id: int, student_id: int, session_id: str, csrftoken: str) -> None:
    ref = db.reference(f'/users')
    ref.child(str(user_id)).set(
        {
            'student_id': student_id,
            'session_id': session_id,
            'csrf_token': csrftoken
        }
    )


def remove_user(user_id: int):
    ref = db.reference(f'/users/{user_id}')
    ref.delete()


def get_user(user_id: int) -> OrderedDict or None:
    ref = db.reference(f'/users/{user_id}')
    return ref.get()
