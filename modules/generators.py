import logging

from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from requests.sessions import Session
import plotly.express as px
from datetime import datetime, timedelta
from transliterate import translit
from os.path import isfile
from modules import api, database
import pandas as pd
import calendar
import json

COLORS = [
    '#e6194B',
    '#3cb44b',
    '#ffe119',
    '#4363d8',
    '#f58231',
    '#911eb4',
    '#42d4f4',
    '#f032e6',
    '#bfef45',
    '#fabed4',
    '#469990',
    '#dcbeff',
    '#9A6324',
    '#fffac8',
    '#800000',
    '#aaffc3',
    '#808000',
    '#ffd8b1',
    '#000075'
]


def generate_inline_markup(*args) -> InlineKeyboardMarkup:
    """
    Generate inline markup by list of dicts with parameters
    """
    keyboard = InlineKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    for element in args:
        if type(element) == dict:
            keyboard.add(InlineKeyboardButton(**element))
        else:
            keyboard.add(*[InlineKeyboardButton(**button) for button in element])
    return keyboard


def get_week() -> list:
    res = []
    day = datetime.now()
    for i in range(8):
        now = day + timedelta(days=i)
        res.append((now.strftime("%Y-%m-%d"), calendar.day_name[now.weekday()]))
    return res


def get_today() -> str:
    now = datetime.now()
    return now.strftime("%Y-%m-%d")


def get_shifted_day(shift: int) -> str:
    now = datetime.now() + timedelta(days=shift)
    return now.strftime("%Y-%m-%d")


def __bold(text: str) -> str:
    return f'<b>{text}</b>'


def __to_integer(dt_time):
    return 10000 * dt_time.year + 100 * dt_time.month + dt_time.day


def __get_time(date: str) -> str:
    return date.split('T')[1].split('+')[0]


def __adjust_text(text: str, char: str, size: int) -> str:
    len_text = len(text)
    just_size = (size - len_text - 2) // 2
    return char * just_size + ' ' + text + ' ' + char * just_size


def draw_day(session: Session, current_date: str, safe_file_name: str) -> bool:
    color_map = dict(not_available="#DDDDDD")
    graph_data = []
    default_colors = False
    for sport in api.get_full_day(session, current_date):
        if color_map.get(sport['title']) is None:
            if len(color_map) < len(COLORS):
                color_map[sport['title']] = COLORS[len(color_map)]
            else:
                default_colors = True
        cant_check_in = not sport['extendedProps']['checked_in'] and not sport['extendedProps']['can_check_in']

        symbol = ""
        if sport['extendedProps']['checked_in']:
            symbol = " ✔ "

        start_datetime = datetime.fromisoformat(sport['start'])
        end_datetime = datetime.fromisoformat(sport['end'])
        graph_data.append({
            'Task': sport['title'],
            'Start': start_datetime,
            'Finish': end_datetime,
            'Sport type': sport['title'],
            "Color": sport['title'] if not cant_check_in else "not_available",
            'Text': symbol + __bold(f'{start_datetime.strftime("%H:%M")}-{end_datetime.strftime("%H:%M")}') + symbol
        })
    if not graph_data:
        return False
    df = pd.DataFrame(graph_data)
    fig = px.timeline(df, x_start="Start", x_end="Finish", y="Sport type", color="Color", text='Text',
                      color_discrete_map=None if default_colors else color_map, width=1920, height=1080)
    fig.update_xaxes(tickvals=[f'{current_date}T{h}:00:00' for h in range(24)])
    fig.update_layout(
        showlegend=False,
        font=dict(size=14)
    )

    fig.write_image(f'images/{safe_file_name}.png')
    return True


def draw_my_week(session: Session, safe_file_name: str) -> bool:
    color_map = dict()
    graph_data = []
    default_colors = False
    start_date = get_today()
    end_date = get_shifted_day(8)
    start = datetime.fromisoformat(start_date)
    for sport in api.get_full_time_period(session, start_date, end_date):
        if not sport['extendedProps']['checked_in']:
            continue
        start_datetime = datetime.fromisoformat(sport['start'])
        end_datetime = datetime.fromisoformat(sport['end'])
        start_time = datetime(
            hour=start_datetime.hour,
            minute=start_datetime.minute,
            day=start.day,
            month=start.month,
            year=start.year
        )
        end_time = datetime(
            hour=end_datetime.hour,
            minute=end_datetime.minute,
            day=start.day,
            month=start.month,
            year=start.year
        )
        day = start_datetime.strftime('%Y/%m/%d')

        if color_map.get(sport['title']) is None:
            if len(color_map) < len(COLORS):
                color_map[sport['title']] = COLORS[len(color_map)]
            else:
                default_colors = True
        graph_data.append({
            'Day': day + ' (' + calendar.day_name[start_datetime.weekday()] + ')',
            'FullTime': __to_integer(start_datetime),
            'Start': start_time,
            'Finish': end_time,
            'Title': sport['title'],
            'Text': f'{start_time.strftime("%H:%M")}-{end_time.strftime("%H:%M")}'
        })
    if not graph_data:
        return False
    df = pd.DataFrame(graph_data)
    fig = px.timeline(df, x_start="Start", x_end="Finish", y="Day", text='Text', color='Title',
                      color_discrete_map=None if default_colors else color_map, width=2048, height=1080)
    fig.update_xaxes(showticklabels=False)
    fig.update_layout(
        font=dict(size=30)
    )

    fig.write_image(f'images/{safe_file_name}.png')
    return True


def generate_today_image(user_id: int, session: Session) -> bool:
    return generate_date_image(get_today(), user_id, session)


def generate_date_image(date: str, user_id: int, session: Session, rewrite: bool = False) -> bool:
    if isfile(f'images/{user_id}.png') and not rewrite:
        return True
    return draw_day(session=session, current_date=date, safe_file_name=str(user_id))


def generate_confirmation_inline():
    return generate_inline_markup(
        {'text': 'Yes, I am sure', 'callback_data': 'conf/sure'},
        {'text': 'No', 'callback_data': f'conf/no'},
    )


def generate_date_inline(date: str):
    return generate_inline_markup(
        {'text': 'My sports', 'callback_data': f'my/{date}'},
        {'text': 'Checkin to sport', 'callback_data': f'ckin/{date}'},
        {'text': 'Change day', 'callback_data': 'change'}
    )


def generate_my_inline(date: str):
    return generate_inline_markup(
        {'text': 'Update info', 'callback_data': f'my/{date}'},
        {'text': 'Set autocheckin', 'callback_data': f'auto/{date}'},
        {'text': '« Back', 'callback_data': f'date/{date}'}
    )


def generate_date_caption(date: str):
    now = datetime.fromisoformat(date)
    return f'Sport schedule for *{calendar.day_name[now.weekday()]} ({date})*\n\nHere is the list of commands what this bot can do:'


def generate_my_caption(session: Session):
    user_statistics = api.get_user_statistics(session)
    return f'Your sport schedule for the upcoming week\n\n' \
           f'Your statistics:\n' \
           f'• Current sport hours: *{user_statistics["hours"]}*\n' \
           f'• You are better than *{user_statistics["better_than"]}%* of students'


def generate_date_courses_buttons(date: str, session: Session):
    res = []
    sports = api.get_full_day(session, date)
    used = dict()
    unique_sports = [(sport['title'], sport['extendedProps']['group_id']) for sport in sports]
    for unique in unique_sports:
        if used.get(unique[0]):
            continue
        res.append({
            'text': unique[0],
            'callback_data': f'gid/{date}/{unique[1]}'
        })
        used[unique[0]] = True
    res = res[::-1]
    res.append({'text': '« Back', 'callback_data': f'date/{date}'})
    return generate_inline_markup(*res)


def generate_date_group_time_buttons(date: str, group_id: int, session: Session, user_id: int):
    res = []
    sports = api.get_full_day(session, date)
    trainings = [sport for sport in sports if sport['extendedProps']['group_id'] == group_id]
    for sport in trainings:
        training_info = api.get_training_info(session, sport['extendedProps']['id'])
        training_id = training_info['training']['id']
        notified_users = database.get_notification_users(training_id)

        capacity = training_info['training']['group']['capacity']
        load = capacity - training_info['training']['load']

        l_symbol = r_symbol = ""
        if sport['extendedProps']['checked_in']:
            r_symbol = "✅"
        elif not sport['extendedProps']['can_check_in']:
            r_symbol = "❌"
            if load == 0:
                l_symbol = '🔔' if user_id in notified_users else '🔕'
        res.append([
            {
                'text': f"{sport['start'].split('T')[1].split('+')[0][:-3]}-{sport['end'].split('T')[1].split('+')[0][:-3]} ({load}/{capacity}) {r_symbol}",
                'callback_data': f'tid/{sport["extendedProps"]["id"]}',
                'time': datetime.fromisoformat(sport['start']).timestamp()
            }
        ]
        )
        if l_symbol:
            res[-1].append(
                {
                    'text': f"Notification {'on' if user_id in notified_users else 'off'} {l_symbol} ",
                    'callback_data': f'ntid/{sport["extendedProps"]["id"]}',
                    'time': datetime.now().timestamp()
                }
            )
    res.sort(key=lambda a: a[0]['time'])
    res.append([{'text': '« Back', 'callback_data': f'ckin/{date}'}])
    return generate_inline_markup(*res)


def generate_group_time_caption(group_id: int, session: Session):
    teachers = api.get_teachers(session, group_id)
    teacher_markdown = []
    for teacher in teachers:
        full_name = translit(teacher['trainer_first_name'] + ' ' + teacher['trainer_last_name'], language_code='ru',
                             reversed=True)
        teacher_markdown.append(
            f'{full_name} {teacher["trainer_email"]}'
        )
    teacher_markdown = '\n'.join(teacher_markdown)
    return f"Teachers emails:\n{teacher_markdown}\n\nSelect time when you want to checkin:\n\n"


def generate_auto_checkin_list_caption():
    return f"Please select sport that you want to visit every week:"


def generate_auto_checkin_list_markup(session: Session, date: str, user_id: int):
    start_date = get_today()
    end_date = get_shifted_day(8)


    sport_to_id = dict()
    for sport in api.get_full_time_period(session, start_date, end_date):
        if not sport['extendedProps']['checked_in']:
            continue
        group_id = sport['extendedProps']['group_id']
        weekday = datetime.fromisoformat(sport['start']).weekday()
        start_time = datetime.fromisoformat(sport['start']).strftime('%H:%M')
        end_time = datetime.fromisoformat(sport['end']).strftime('%H:%M')
        parsed_string = f"{group_id}|{weekday}|{start_time}-{end_time}"
        title = sport['title']

        if sport_to_id.get(title) is None:
            sport_to_id[title] = []
        sport_to_id[title].append({'id': parsed_string, 'text': f'{calendar.day_name[weekday]} {start_time}-{end_time}'})

    res = []
    for sport_title in sport_to_id:
        res.append([
            {
                'text': f'===== {sport_title} =====',
                'callback_data': 'why'
            }
        ])
        for training in sport_to_id[sport_title]:
            auto_checked_in = database.check_auto_checkin(user_id, training['id'])
            res.append([
                {
                    'text': f"{training['text']} " + ('🔁' if auto_checked_in else ''),
                    'callback_data': f'aid/{date}/{training["id"]}'
                }
            ])

    res.append([{'text': '« Back', 'callback_data': f'my/{date}'}])

    return generate_inline_markup(*res)


def parse_and_save_whole_semester(session: Session):
    semester_start_end = api.get_semester_start_end_dates(session)
    res = api.get_full_time_period(  # get whole semester trainings
        session,
        semester_start_end[0].strftime("%Y-%m-%d"),
        semester_start_end[1].strftime("%Y-%m-%d")
    )

    res = sorted(res, key=lambda s: datetime.fromisoformat(s['start']))

    # Drop non-required info
    for sport in res:
        sport.pop('allDay')
        sport.pop('title')
        sport['extendedProps'].pop('can_edit')
        sport['extendedProps'].pop('can_grade')
        sport['extendedProps'].pop('training_class')
        sport['extendedProps'].pop('can_check_in')
        sport['extendedProps'].pop('checked_in')
        sport['start'] = sport['start'].split('+')[0]
        sport['end'] = sport['end'].split('+')[0]

    # Parse sport to have O(1) access to training id's by group_id/weekday/start-end time
    parsed_sports = dict()
    for sport in res:
        start_time = datetime.fromisoformat(sport['start']).strftime('%H:%M')
        end_time = datetime.fromisoformat(sport['end']).strftime('%H:%M')
        weekday = datetime.fromisoformat(sport['start']).weekday()
        group_id = sport['extendedProps']['group_id']

        parsed_string = f"{group_id}/{weekday}/{start_time}-{end_time}"
        if parsed_sports.get(parsed_string) is None:  # If this group appeared first time
            parsed_sports[parsed_string] = []  # Create new key
        parsed_sports[parsed_string].append(sport['extendedProps']['id'])  # Add training_id

    with open('semester_trainings.json', 'w') as file:
        file.write(json.dumps(parsed_sports, indent=4))


def get_training_ids_to_auto_checkin(session: Session, training_key: str) -> list:
    with open('semester_trainings.json', 'r') as file:
        trainings = json.load(file)

    if trainings.get(training_key) is None:  # In case when semester changed, we want all file to reload and be up-to-date
        parse_and_save_whole_semester(session)
        with open('semester_trainings.json', 'r') as file:
            trainings = json.load(file)

    if trainings.get(training_key) is None:  # If nothing found (strangely and should not happen), no ids are found
        logging.warning(f'generator.py -> get_training_ids_to_auto_checkin -> no trainings found for key "{training_key}"')
        return []

    return trainings[training_key]
