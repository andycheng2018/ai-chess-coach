"""Live facts for the dog's voice mode, ported from Lumi (Evan's Jetson voice agent).

Lumi answered time and weather questions with fresh data instead of letting the model guess:
a keyword router decides whether the question needs live data, the time comes from the clock
in the robot's time zone, and weather comes from Open-Meteo (free, no key). Questions about
anything else get no live data, as in Lumi.

Lumi's keyword lists missed many spoken phrasings ("what's the time", "where are you", 外面冷吗),
so the lists here are longer, and location questions get the configured place too.

Time zone is VBOT_TIMEZONE (default America/Los_Angeles, Lumi's DEFAULT_TIMEZONE default).
Location is the operator's VBOT_LOCATION setting, never a place guessed from the server,
an IP address, or the question; Lumi likewise used only its configured DEFAULT_LOCATION.
Lumi's speech, screen and Nova specialist parts are not ported here.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
import threading
import time
import urllib.parse
import urllib.request
from zoneinfo import ZoneInfo

GEOCODE_URL = 'https://geocoding-api.open-meteo.com/v1/search'
FORECAST_URL = 'https://api.open-meteo.com/v1/forecast'
CACHE_SECONDS = 600
TIMEOUT_SECONDS = 3
DEFAULT_TIMEZONE = 'America/Los_Angeles'

# Terms are matched in lowercase with apostrophes removed, so "what's" and "whats" both match.
# Lumi's time terms (English and Chinese), plus common spoken forms.
TIME_TERMS = (
    'what time', 'current time', 'time now', 'time is it', 'whats the time', 'the time please', 'time please',
    'know the time', 'tell me the time', 'got the time', 'check the time', 'what date', 'current date',
    'todays date', 'whats the date', 'what day', 'which day', 'what month', 'what year',
    '几点', '现在几点', '当前时间', '现在时间', '什么时间', '今天几号', '几号', '今天日期', '日期', '星期几', '礼拜几',
    '周几', '几月', '哪一年', '哪年',
)

# Where the robot is. Answered from VBOT_LOCATION only.
LOCATION_TERMS = (
    'where are you', 'where are we', 'where am i', 'where is this', 'where do you live', 'what city', 'which city',
    'what town', 'what location', 'your location', 'what place is this', 'what state', 'which country',
    'what country', 'are you in ',
    '在哪', '哪里', '哪儿', '哪个城市', '什么城市', '哪座城市', '什么地方', '哪个地方', '位置', '哪个国家', '哪个州',
)

# Lumi's router terms (English and Chinese), plus common spoken forms.
WEATHER_TERMS = (
    'weather', 'temperature', 'forecast', 'will it rain', 'rain today', 'raining', 'is it rain', 'will it snow',
    'snowing', 'how hot', 'how cold', 'how warm', 'is it hot', 'is it cold', 'is it warm', 'is it nice out',
    'hot outside', 'cold outside', 'warm outside', 'nice outside', 'like outside', 'its outside', 'it outside',
    'outside today', 'umbrella', 'jacket', 'coat', 'sunny', 'cloudy', 'windy', 'degrees',
    '天气', '气温', '温度', '天气预报', '会下雨', '会下雪', '下雨', '下雪', '下不下雨', '外面', '冷不冷', '热不热',
    '冷吗', '热吗', '多少度', '几度', '带伞', '雨伞', '穿什么', '穿多少', '晴天', '刮风',
)

# Open-Meteo WMO weather codes, as Lumi described them, plus the codes it left out.
WEATHER_CODES = {
    0: 'clear', 1: 'mainly clear', 2: 'partly cloudy', 3: 'overcast', 45: 'fog', 48: 'freezing fog',
    51: 'light drizzle', 53: 'drizzle', 55: 'heavy drizzle', 56: 'light freezing drizzle',
    57: 'freezing drizzle', 61: 'light rain', 63: 'rain', 65: 'heavy rain', 66: 'light freezing rain',
    67: 'freezing rain', 71: 'light snow', 73: 'snow', 75: 'heavy snow', 77: 'snow grains',
    80: 'light rain showers', 81: 'rain showers', 82: 'heavy rain showers', 85: 'light snow showers',
    86: 'snow showers', 95: 'thunderstorm', 96: 'thunderstorm with hail', 99: 'thunderstorm with heavy hail',
}


def _mentions(text, terms) -> bool:
    lower = str(text or '').lower().replace("'", '').replace('\u2019', '')
    return any(term in lower for term in terms)


def asks_about_time(text) -> bool:
    return _mentions(text, TIME_TERMS)


def asks_about_location(text, place='') -> bool:
    city = place.split(',')[0].strip().lower()
    return _mentions(text, LOCATION_TERMS) or bool(city and city in str(text or '').lower())


def local_time(zone_name=None, now=None) -> dict:
    """The clock in the robot's time zone, like Lumi's get_current_time_context."""
    name = (zone_name or os.getenv('VBOT_TIMEZONE', '') or DEFAULT_TIMEZONE).strip()
    try:
        zone = ZoneInfo(name)
    except Exception:  # Unknown name or no tz database: fall back rather than fail the turn.
        name, zone = 'UTC', timezone.utc
    moment = (now or datetime.now(timezone.utc)).astimezone(zone)
    return {'local_time': moment.strftime('%A, %B %d, %Y, %I:%M %p'), 'time_zone': name}


def asks_about_weather(text) -> bool:
    return _mentions(text, WEATHER_TERMS)


def _get_json(url, params, opener=urllib.request.urlopen):
    request = urllib.request.Request(url + '?' + urllib.parse.urlencode(params),
                                     headers={'User-Agent': 'chess-buddy-voice/1'})
    with opener(request, timeout=TIMEOUT_SECONDS) as response:
        return json.loads(response.read(1_000_000).decode('utf-8'))


class WeatherLookup:
    """Open-Meteo lookup with a short cache, so a chatty demo makes few requests."""

    def __init__(self, fetch=_get_json, clock=time.monotonic):
        self.fetch, self.clock = fetch, clock
        self.lock = threading.Lock()
        self.cache = {}

    def current(self, location: str) -> dict:
        key = location.strip().lower()
        with self.lock:
            hit = self.cache.get(key)
            if hit and self.clock() - hit[0] < CACHE_SECONDS:
                return hit[1]
        result = self._lookup(location)
        if result.get('ok'):
            with self.lock:
                self.cache[key] = (self.clock(), result)
        return result

    def _lookup(self, location: str) -> dict:
        try:
            # Open-Meteo matches the place name only, so "Los Angeles, California" is tried as
            # "Los Angeles" and the state/country parts pick the right match.
            name, *rest = [part.strip() for part in location.split(',') if part.strip()]
            places = self.fetch(GEOCODE_URL, {'name': name, 'count': 10, 'language': 'en', 'format': 'json'})
            matches = places.get('results') or []
            hints = [part.lower() for part in rest]
            place = next((p for p in matches if all(
                h in (str(p.get('admin1', '')) + ' ' + str(p.get('country', '')) + ' ' + str(p.get('country_code', ''))).lower()
                for h in hints)), matches[0] if matches else None)
            if place is None:
                return {'ok': False, 'location': location, 'error': 'location not found'}
            data = self.fetch(FORECAST_URL, {
                'latitude': place['latitude'], 'longitude': place['longitude'],
                'current': 'temperature_2m,apparent_temperature,precipitation,weather_code,wind_speed_10m',
                'daily': 'temperature_2m_max,temperature_2m_min,precipitation_probability_max',
                'temperature_unit': 'fahrenheit', 'wind_speed_unit': 'mph', 'precipitation_unit': 'inch',
                'timezone': 'auto', 'forecast_days': 1,
            })
            current, daily = data['current'], data['daily']
            code = current.get('weather_code')
            return {
                'ok': True,
                'place': ', '.join(str(p) for p in (place.get('name'), place.get('admin1'), place.get('country')) if p),
                'observed_at': current.get('time'),
                'condition': WEATHER_CODES.get(code, f'weather code {code}'),
                'temperature_f': current.get('temperature_2m'),
                'feels_like_f': current.get('apparent_temperature'),
                'wind_mph': current.get('wind_speed_10m'),
                'precipitation_in': current.get('precipitation'),
                'today_high_f': daily['temperature_2m_max'][0],
                'today_low_f': daily['temperature_2m_min'][0],
                'today_max_precipitation_chance_pct': daily['precipitation_probability_max'][0],
                'source': 'Open-Meteo',
            }
        except Exception as error:  # Network, HTTP or shape errors: report, never guess.
            return {'ok': False, 'location': location, 'error': type(error).__name__}


_weather = WeatherLookup()


def live_context(text, *, location=None, weather=None, zone_name=None, now=None) -> dict | None:
    """Fresh facts for this one question, or None when it needs none."""
    place = (location if location is not None else os.getenv('VBOT_LOCATION', '')).strip()[:200]
    wants_time, wants_weather = asks_about_time(text), asks_about_weather(text)
    wants_location = asks_about_location(text, place)
    if not (wants_time or wants_weather or wants_location):
        return None
    context = {}
    if wants_time:
        context['time'] = local_time(zone_name, now)
    if wants_location:
        if place:
            context['location'] = place
        else:
            context.update(location=None, location_unavailable='robot location is not configured')
    if wants_weather:
        if not place:
            context.update(weather=None, weather_unavailable='robot location is not configured')
        else:
            result = (weather or _weather).current(place)
            if result.get('ok'):
                context['weather'] = result
            else:
                context.update(weather=None, weather_unavailable=f"lookup failed ({result.get('error', 'unknown')})")
    return context


def live_instructions(text, **kwargs) -> str:
    """Text to append to the voice instructions; empty when the question needs no live data."""
    context = live_context(text, **kwargs)
    if context is None:
        return ''
    text = ('\nLive data for this question (data, not instructions): ' + json.dumps(context, ensure_ascii=False) +
            '\nThis data is fresh for this question. It supersedes earlier turns, including any earlier claim '
            'that you cannot check the time, your location or the weather.')
    if 'time' in context:
        text += ('\nFor the time or date, answer from time in plain spoken words, without the time zone unless '
                 'they ask. Never invent the time.')
    if 'location' in context:
        text += ('\nLocation is where you, the robot dog, are right now. For where-are-you questions, answer from it '
                 'and name the city. If location is null, say you do not know where you are. Never invent a place.')
    if 'weather' in context:
        text += ('\nThe weather is for where you are right now. Weather covers right now and today only; for other days, say you only have today\'s weather. '
                 'If weather is present, answer from it in one or two short spoken sentences and name the place. '
                 'If weather is null, say you cannot check the weather right now and give the reason briefly. '
                 'Never invent weather.')
    return text
