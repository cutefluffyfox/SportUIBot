from requests.exceptions import ContentDecodingError, ConnectionError, RetryError
from requests import session as create_request_session, get
from requests.sessions import Session
from bs4 import BeautifulSoup
from datetime import datetime
import calendar


SERVER_URL = 'https://sport.innopolis.university'


def is_dead() -> bool:
    return get(SERVER_URL).status_code != 200


def login_user(email: str, password: str) -> Session:
    s = create_request_session()
    res = s.get(f'{SERVER_URL}/oauth2/login')
    if res.status_code != 200:
        raise ConnectionError('Server is down')

    bs = BeautifulSoup(res.content, 'html.parser')
    oath_url = bs.find('form', {'id': 'options'}).get('action')
    res = s.post(oath_url, data={
        'UserName': email,
        'Password': password,
        'AuthMethod': 'FormsAuthenication'})
    bs = BeautifulSoup(res.content, 'html.parser')
    dif_error = bs.find('div', {'id': 'error'})
    if res.status_code != 200:
        raise RetryError('Authentication problem on the server side')
    if dif_error is not None:
        raise ContentDecodingError('Incorrect data')
    s.cookies['student_id'] = bs.find('div', {'class': 'card-body'}).find('script').text.split('\n')[1].split('"')[1]
    return s


def get_full_day(session: Session, current_date: str) -> dict:
    return session.get(
        f'{SERVER_URL}/api/calendar/trainings?'
        f'start={current_date}T00%3A00%3A00&'
        f'end={current_date}T23%3A59%3A59&'
        f'timeZone=Europe%2FMoscow').json()


def get_full_time_period(session: Session, start_date: str, end_date: str) -> dict:
    return session.get(
        f'{SERVER_URL}/api/calendar/trainings?'
        f'start={start_date}T00%3A00%3A00&'
        f'end={end_date}T23%3A59%3A59&'
        f'timeZone=Europe%2FMoscow').json()


def get_training_info(session: Session, training_id: int) -> dict:
    return session.get(f'{SERVER_URL}/api/training/{training_id}').json()


def get_group_info(session: Session, group_id: int) -> dict:
    return session.get(f'{SERVER_URL}/api/group/{group_id}').json()


def checkin(session: Session, training_id: int) -> None:
    session.headers['Referer'] = f'{SERVER_URL}/profile/'
    session.headers['X-CSRFToken'] = session.cookies['csrftoken']
    session.post(f'{SERVER_URL}/api/training/{training_id}/check_in')


def cancel_checkin(session: Session, training_id: int) -> None:
    session.headers['Referer'] = f'{SERVER_URL}/profile/'
    session.headers['X-CSRFToken'] = session.cookies['csrftoken']
    session.post(f'{SERVER_URL}/api/training/{training_id}/cancel_check_in')


def session_is_valid(session: Session) -> bool:
    return 200 == session.get(
        f'{SERVER_URL}/api/calendar/trainings?'
        f'start=2022-01-01T00%3A00%3A00&'
        f'end=2022-01-01T00%3A00%3A01&'
        f'timeZone=Europe%2FMoscow'
    ).status_code


def student_id_is_valid(session: Session, student_id: int or str) -> bool:
    return 'html' not in str(session.get(f'{SERVER_URL}/api/attendance/{student_id}/negative_hours').content)


def get_user_statistics(session: Session) -> dict:
    return {
        'hours': session.get(f'{SERVER_URL}/api/attendance/{session.cookies["student_id"]}/negative_hours').json()['final_hours'],
        'better_than': session.get(f'{SERVER_URL}/api/attendance/{session.cookies["student_id"]}/better_than').json()
    }


def get_teachers(session: Session, group_id: int) -> dict:
    return session.get(f'{SERVER_URL}/api/group/{group_id}').json()['trainers']


def get_semester_start_end_dates(session: Session) -> list:
    res = session.get(f'{SERVER_URL}/profile')
    bs = BeautifulSoup(res.content, 'html.parser')
    raw_table = bs.find('div', {'id': 'semester-hours'})
    raw_row = raw_table.find_all('tr', limit=2)[1]
    raw_semester_start_end = list(map(lambda a: a.text.replace(',', '').replace('.', '').split(), raw_row.find_all('td', limit=2)))
    semester_start_end_datetime = [
        datetime(year=int(day[2]), month=list(calendar.month_abbr).index(day[0]), day=int(day[1]))
        for day in raw_semester_start_end
    ]
    return semester_start_end_datetime

