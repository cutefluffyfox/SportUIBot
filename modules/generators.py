from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from requests.sessions import Session
import plotly.express as px
from datetime import datetime, timedelta
from os.path import isfile
from modules import api, database
import pandas as pd
import calendar


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
    '#000075',
    '#a9a9a9',
    '#ffffff',
    '#000000'
]


def generate_inline_markup(*args) -> InlineKeyboardMarkup:
    """
    Generate inline markup by list of dicts with parameters
    """
    keyboard = InlineKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    for button in args:
        keyboard.add(InlineKeyboardButton(**button))
    return keyboard


def get_week() -> list:
    res = []
    day = datetime.now()
    for i in range(8):
        now = day + timedelta(days=i)
        res.append((f'{now.year}-{now.month}-{now.day}', calendar.day_name[now.weekday()]))
    return res


def get_today() -> str:
    now = datetime.now()
    return f'{now.year}-{now.month}-{now.day}'


def get_shifted_day(shift: int) -> str:
    now = datetime.now() + timedelta(days=shift)
    return f'{now.year}-{now.month}-{now.day}'


def __bold(text: str) -> str:
    return f'<b>{text}</b>'


def __to_integer(dt_time):
    return 10000 * dt_time.year + 100 * dt_time.month + dt_time.day


def __get_time(date: str) -> str:
    return date.split('T')[1].split('+')[0]


def draw_day(session: Session, current_date: str, safe_file_name: str):
    color_map = dict()
    graph_data = []
    default_colors = False
    for sport in api.get_full_day(session, current_date):
        if color_map.get(sport['title']) is None:
            if len(color_map) < len(COLORS):
                color_map[sport['title']] = COLORS[len(color_map)]
            else:
                default_colors = True
        start_datetime = datetime.fromisoformat(sport['start'])
        end_datetime = datetime.fromisoformat(sport['end'])
        graph_data.append({
            'Task': sport['title'],
            'Start': start_datetime,
            'Finish': end_datetime,
            'Sport type': sport['title'],
            'Text': __bold(f'{start_datetime.strftime("%H:%M")}-{end_datetime.strftime("%H:%M")}')
        })
    df = pd.DataFrame(graph_data)
    fig = px.timeline(df, x_start="Start", x_end="Finish", y="Sport type", color="Sport type", text='Text',
                      color_discrete_map=None if default_colors else color_map, width=1920, height=1080)
    fig.update_xaxes(tickvals=[f'{current_date}T{h}:00:00' for h in range(24)])
    fig.update_layout(
        showlegend=False,
        font=dict(size=16)
    )

    fig.write_image(f'images/{safe_file_name}.png')


def draw_week_by_sport_type(session: Session, start_date: str, end_date: str, sport_name: str, safe_file_name: str):
    color_map = dict()
    graph_data = []
    default_colors = False
    start = datetime.fromisoformat(start_date)
    for sport in api.get_full_time_period(session, start_date, end_date):
        if sport['title'] != sport_name:
            continue
        start_datetime = datetime.fromisoformat(sport['start'])
        end_datetime = datetime.fromisoformat(sport['end'])
        start_time = datetime(hour=start_datetime.hour, minute=start_datetime.minute, day=start.day, month=start.month,
                              year=start.year)
        end_time = datetime(hour=end_datetime.hour, minute=end_datetime.minute, day=start.day, month=start.month,
                            year=start.year)
        day = datetime(day=start_datetime.day, month=start_datetime.month, year=start_datetime.year).strftime(
            '%Y/%m/%d')
        weekday = calendar.day_name[start_datetime.weekday()]

        if color_map.get(weekday) is None:
            if len(color_map) < len(COLORS):
                color_map[weekday] = COLORS[len(color_map)]
            else:
                default_colors = True
        graph_data.append({
            'Day': day,
            'FullTime': __to_integer(start_datetime),
            'Start': start_time,
            'Finish': end_time,
            'Weekday': weekday,
            'Text': f'{start_time.strftime("%H:%M")}-{end_time.strftime("%H:%M")}'
        })

    df = pd.DataFrame(graph_data).sort_values(by='FullTime', ignore_index=True)
    fig = px.timeline(df, x_start="Start", x_end="Finish", y="Day", text='Text', color='Weekday',
                      color_discrete_map=None if default_colors else color_map, width=2048, height=1080)
    fig.update_xaxes(tickvals=[f'{start_date}T{h}:00:00' for h in range(24)])

    fig.write_image(f'images/{safe_file_name}.png')


def draw_my_week(session: Session, safe_file_name: str):
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
        start_time = datetime(hour=start_datetime.hour, minute=start_datetime.minute, day=start.day, month=start.month,
                              year=start.year)
        end_time = datetime(hour=end_datetime.hour, minute=end_datetime.minute, day=start.day, month=start.month,
                            year=start.year)
        day = datetime(day=start_datetime.day, month=start_datetime.month, year=start_datetime.year).strftime(
            '%Y/%m/%d')

        if color_map.get(sport['title']) is None:
            if len(color_map) < len(COLORS):
                color_map[sport['title']] = COLORS[len(color_map)]
            else:
                default_colors = True
        graph_data.append({
            'Day': day,
            'FullTime': __to_integer(start_datetime),
            'Start': start_time,
            'Finish': end_time,
            'Title': sport['title'],
            'Text': f'{start_time.strftime("%H:%M")}-{end_time.strftime("%H:%M")}'
        })

    df = pd.DataFrame(graph_data).sort_values(by='FullTime', ignore_index=True)
    fig = px.timeline(df, x_start="Start", x_end="Finish", y="Day", text='Text', color='Title',
                      color_discrete_map=None if default_colors else color_map, width=2048, height=1080)
    fig.update_xaxes(tickvals=[f'{start_date}T{h}:00:00' for h in range(24)])
    fig.update_layout(
        font=dict(size=30)
    )

    fig.write_image(f'images/{safe_file_name}.png')


def generate_today_image(session: Session):
    generate_date_image(get_today(), session)


def generate_date_image(date: str, session: Session):
    if isfile(f'images/{date}.png'):
        return
    draw_day(session=session, current_date=date, safe_file_name=date)


def generate_date_inline(date: str):
    return generate_inline_markup(
        {'text': 'My sports', 'callback_data': f'my/{date}'},
        {'text': 'Checkin to sport', 'callback_data': f'ckin/{date}'},
        {'text': 'Change day', 'callback_data': 'change'}
    )


def generate_my_inline(date: str):
    return generate_inline_markup(
        {'text': 'Set autocheckin', 'callback_data': 'auto'},
        {'text': 'Back', 'callback_data': f'upd/{date}'}
    )


def generate_date_caption(date: str):
    return f'Sport schedule for {date}\n\nHere is the list of commands what this bot can do:'


def generate_my_caption(session: Session):
    user_statistics = api.get_user_statistics(session)
    return f'Your sport schedule for the upcoming week\n\n' \
           f'Your statistics:\n' \
           f'• Current sport hours: *{user_statistics["hours"]}*\n' \
           f'• You are better than *{user_statistics["better_than"]}%* of students'



def generate_date_courses_buttons(date: str, session: Session):
    res = []
    sports = api.get_full_day(session, date)
    unique_sports = {(sport['title'], sport['extendedProps']['group_id']) for sport in sports}
    for unique in unique_sports:
        res.append({
            'text': unique[0],
            'callback_data': f'gid/{date}/{unique[1]}'
        })
    res.append({'text': 'Cancel', 'callback_data': f'date/{date}'})
    return generate_inline_markup(*res)


def generate_date_group_time_buttons(date: str, group_id: int, session: Session):
    res = []
    sports = api.get_full_day(session, date)
    unique_sports = [sport for sport in sports if sport['extendedProps']['group_id'] == group_id]
    for sport in unique_sports:
        training_info = api.get_training_info(session, sport['extendedProps']['id'])
        symbol = ""
        if sport['extendedProps']['checked_in']:
            symbol = "✅"
        elif not sport['extendedProps']['can_check_in']:
            symbol = "❌"
        capacity = training_info['training']['group']['capacity']
        load = capacity - training_info['training']['load']
        res.append({
            'text': f"{sport['start'].split('T')[1].split('+')[0]}-{sport['end'].split('T')[1].split('+')[0]} ({load}/{capacity}) {symbol}",
            'callback_data': f'tid/{sport["extendedProps"]["id"]}'
        })
    res.append({'text': 'Cancel', 'callback_data': f'ckin/{date}'})
    return generate_inline_markup(*res)
