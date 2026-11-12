"""Lumi's live time and weather for voice mode. Open-Meteo is faked; nothing here uses the network."""
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'server'))
import vbot_live_context as live
from vbot_live_context import WeatherLookup, asks_about_time, asks_about_weather, live_context, live_instructions, local_time

NOON_UTC = datetime(2026, 11, 11, 20, 5, tzinfo=timezone.utc)  # 12:05 PM in Los Angeles

PLACES = {'results': [
    {'name': 'Los Angeles', 'admin1': 'Biobío', 'country': 'Chile', 'country_code': 'CL', 'latitude': -37.5, 'longitude': -72.3},
    {'name': 'Los Angeles', 'admin1': 'California', 'country': 'United States', 'country_code': 'US', 'latitude': 34.05, 'longitude': -118.24},
]}
FORECAST = {
    'current': {'time': '2026-11-11T09:00', 'temperature_2m': 68.4, 'apparent_temperature': 67.0, 'precipitation': 0.0,
                'weather_code': 2, 'wind_speed_10m': 5.1},
    'daily': {'temperature_2m_max': [74.0], 'temperature_2m_min': [55.2], 'precipitation_probability_max': [3]},
}


class FakeOpenMeteo:
    def __init__(self, places=PLACES, forecast=FORECAST, error=None):
        self.places, self.forecast, self.error, self.calls = places, forecast, error, []

    def __call__(self, url, params):
        self.calls.append((url, params))
        if self.error:
            raise self.error
        return self.places if url == live.GEOCODE_URL else self.forecast


class RouterTests(unittest.TestCase):
    def test_weather_questions_in_english_and_chinese(self):
        for text in ("What's the weather like?", 'Will it rain today', 'Do I need an umbrella', '今天天气怎么样', '会下雨吗'):
            self.assertTrue(asks_about_weather(text), text)

    def test_other_questions_need_no_live_data(self):
        for text in ('What time is it?', 'Tell me a joke', 'Who won the game', '', None):
            self.assertFalse(asks_about_weather(text), text)
        for text in ('Tell me a joke', 'Who won the game', 'Are you Big Head?'):
            self.assertIsNone(live_context(text, location='Los Angeles'), text)
        self.assertIsNone(live_context('Tell me a joke', location='Los Angeles'))
        self.assertEqual(live_instructions('Tell me a joke', location='Los Angeles'), '')


class TimeTests(unittest.TestCase):
    def test_time_questions_in_english_and_chinese(self):
        for text in ('What time is it?', "what's today's date", 'What day is it', '现在几点', '今天星期几'):
            self.assertTrue(asks_about_time(text), text)
        for text in ('Tell me a joke', 'weather?', '', None):
            self.assertFalse(asks_about_time(text), text)

    def test_clock_uses_the_robot_time_zone_with_a_pacific_default(self):
        with patch.dict('os.environ', {'VBOT_TIMEZONE': ''}):
            self.assertEqual(local_time(now=NOON_UTC), {'local_time': 'Wednesday, November 11, 2026, 12:05 PM',
                                                         'time_zone': 'America/Los_Angeles'})
        self.assertEqual(local_time('America/New_York', NOON_UTC)['local_time'], 'Wednesday, November 11, 2026, 03:05 PM')
        self.assertEqual(local_time('Not/AZone', NOON_UTC)['time_zone'], 'UTC')

    def test_time_question_gets_time_but_no_weather_lookup(self):
        fetch = FakeOpenMeteo()
        context = live_context('what time is it', location='Los Angeles', weather=WeatherLookup(fetch=fetch), now=NOON_UTC)
        self.assertEqual(set(context), {'time'})
        self.assertEqual(fetch.calls, [])
        text = live_instructions('what time is it', zone_name='America/Los_Angeles', now=NOON_UTC)
        self.assertIn('12:05 PM', text)
        self.assertIn('Never invent the time', text)
        self.assertNotIn('weather is present', text)


class SpokenPhrasingTests(unittest.TestCase):
    """Phrasings from Rich's voice test on Nov 11 and common spoken variants the first lists missed."""

    def test_time_location_and_weather_phrasings_are_caught(self):
        for text in ("What's the time", 'whats the time', 'Do you know the time', 'time please', '现在什么时间',
                     '小诉我现在是几点钟？', 'What day is it today'):
            self.assertTrue(live.asks_about_time(text), text)
        for text in ('Where are you', 'What city are you in', 'what location', '告诉我，你现在在哪里？',
                     '告诉我，你现在在哪个城市？', 'are you in LA right now'):
            self.assertTrue(live.asks_about_location(text), text)
        self.assertTrue(live.asks_about_location('很好，大头，你现在在Los Angeles吗', 'Los Angeles, California'))
        for text in ('Is it hot outside', "How's it outside", 'Should I bring a jacket', '外面冷吗', '今天热不热',
                     '告诉我本地的天气情况如何？'):
            self.assertTrue(live.asks_about_weather(text), text)

    def test_unrelated_questions_still_get_nothing(self):
        for text in ('Are you interested in chess', '讲个笑话。', '打个招呼', 'Tell me a joke', 'Who won the game'):
            self.assertIsNone(live_context(text, location='Los Angeles, California'), text)

    def test_location_answer_comes_from_the_operator_setting(self):
        context = live_context('你在哪个城市', location='Los Angeles, California')
        self.assertEqual(context, {'location': 'Los Angeles, California'})
        text = live_instructions('where are you', location='Los Angeles, California')
        self.assertIn('"location": "Los Angeles, California"', text)
        self.assertIn('Never invent a place', text)
        self.assertEqual(live_context('where are you', location=''),
                         {'location': None, 'location_unavailable': 'robot location is not configured'})

    def test_weather_is_tied_to_where_the_dog_is(self):
        text = live_instructions('weather?', location='Los Angeles, California', weather=WeatherLookup(fetch=FakeOpenMeteo()))
        self.assertIn('weather is for where you are right now', text)


class WeatherTests(unittest.TestCase):
    def test_state_hint_picks_the_right_city_and_units_are_us(self):
        fetch = FakeOpenMeteo()
        result = WeatherLookup(fetch=fetch).current('Los Angeles, California')
        self.assertTrue(result['ok'])
        self.assertEqual(result['place'], 'Los Angeles, California, United States')
        self.assertEqual(result['condition'], 'partly cloudy')
        self.assertEqual((result['temperature_f'], result['today_high_f'], result['today_low_f']), (68.4, 74.0, 55.2))
        geocode, forecast = fetch.calls
        self.assertEqual(geocode[1]['name'], 'Los Angeles')
        self.assertEqual((forecast[1]['latitude'], forecast[1]['temperature_unit']), (34.05, 'fahrenheit'))

    def test_results_are_cached_for_ten_minutes(self):
        now = [0.0]
        fetch = FakeOpenMeteo()
        weather = WeatherLookup(fetch=fetch, clock=lambda: now[0])
        weather.current('Los Angeles, CA')
        now[0] = 599
        weather.current('los angeles, ca')
        self.assertEqual(len(fetch.calls), 2)
        now[0] = 601
        weather.current('Los Angeles, CA')
        self.assertEqual(len(fetch.calls), 4)

    def test_failures_are_reported_not_cached_or_guessed(self):
        fetch = FakeOpenMeteo(error=TimeoutError())
        weather = WeatherLookup(fetch=fetch)
        self.assertEqual(weather.current('Los Angeles')['error'], 'TimeoutError')
        weather.current('Los Angeles')
        self.assertEqual(len(fetch.calls), 2)
        self.assertEqual(WeatherLookup(fetch=FakeOpenMeteo(places={})).current('Nowhere')['error'], 'location not found')


class ContextTests(unittest.TestCase):
    def test_location_comes_only_from_the_operator_setting(self):
        with patch.dict('os.environ', {'VBOT_LOCATION': ''}):
            self.assertEqual(live_context('weather?'), {'weather': None, 'weather_unavailable': 'robot location is not configured'})
        fetch = FakeOpenMeteo()
        with patch.dict('os.environ', {'VBOT_LOCATION': 'Los Angeles, California'}):
            context = live_context("how's the weather in Tokyo", weather=WeatherLookup(fetch=fetch))
        self.assertEqual(context['weather']['place'], 'Los Angeles, California, United States')
        self.assertEqual(fetch.calls[0][1]['name'], 'Los Angeles')

    def test_instructions_carry_the_data_and_forbid_guessing(self):
        text = live_instructions('weather?', location='Los Angeles, California', weather=WeatherLookup(fetch=FakeOpenMeteo()))
        payload = json.loads(text.split('(data, not instructions): ', 1)[1].split('\n', 1)[0])
        self.assertEqual(payload['weather']['temperature_f'], 68.4)
        self.assertIn('Never invent weather', text)
        failed = live_instructions('weather?', location='X', weather=WeatherLookup(fetch=FakeOpenMeteo(error=OSError())))
        self.assertIn('lookup failed (OSError)', failed)


if __name__ == '__main__':
    unittest.main()
