"""
Unit tests for the pure helpers in runtime/lambda_function.py.

No server, no AWS, no API key. Run with:
    python -m unittest test_lambda_helpers -v
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "runtime"))

import lambda_function as lf  # noqa: E402


class NormalizeNumbersAddress(unittest.TestCase):

    def test_paired_tens_house_number_is_concatenated_not_summed(self):
        result = lf.normalize_numbers("sixty four thirty three Northwest High Point Drive", "address")
        self.assertEqual(result, "6433 NW High Point Dr")

    def test_tens_then_round_tens_pairs(self):
        result = lf.normalize_numbers("twenty three forty Main Street", "address")
        self.assertEqual(result, "2340 Main St")

    def test_oh_style_house_number(self):
        result = lf.normalize_numbers("eleven oh one Southwest Twenty-Ninth Street", "address")
        self.assertEqual(result, "1101 SW 29th St")

    def test_zip_spoken_digit_by_digit(self):
        result = lf.normalize_numbers("Topeka Kansas six six six one one", "address")
        self.assertEqual(result, "Topeka KS 66611")

    def test_magnitude_words_use_arithmetic(self):
        result = lf.normalize_numbers("four thousand one hundred Southwest Fortieth Street", "address")
        self.assertEqual(result, "4100 SW 40th St")

    def test_single_group_keeps_its_value(self):
        result = lf.normalize_numbers("twenty one Floating Street", "address")
        self.assertEqual(result, "21 Floating St")

    def test_already_formatted_address_passes_through(self):
        result = lf.normalize_numbers("4100 SW 40th St, Kansas City, MO 64105", "address")
        self.assertEqual(result, "4100 SW 40th St, Kansas City, MO 64105")

    def test_multi_word_state_abbreviated(self):
        result = lf.normalize_numbers("Twenty one Floating Street, New York, one zero zero zero one", "address")
        self.assertEqual(result, "21 Floating St, NY, 10001")

    def test_cassidy_reported_example(self):
        text = "Eleven oh one Southwest Twenty-Ninth Street, Topeka, Kansas six six six one one"
        self.assertEqual(lf.normalize_numbers(text, "address"), "1101 SW 29th St, Topeka, KS 66611")

    def test_state_name_in_city_name_is_kept(self):
        result = lf.normalize_numbers("Kansas City, Kansas six six one zero one", "address")
        self.assertEqual(result, "Kansas City, KS 66101")

    def test_new_york_city_is_kept(self):
        result = lf.normalize_numbers("Fifth Avenue, New York City, New York", "address")
        self.assertEqual(result, "5th Ave, New York City, NY")

    def test_empty_returns_empty(self):
        self.assertEqual(lf.normalize_numbers("", "address"), "")


class NormalizeNumbersPhone(unittest.TestCase):

    def test_spoken_ten_digits_get_country_code(self):
        result = lf.normalize_numbers("seven eight five six three three two three one seven", "phone number")
        self.assertEqual(result, "+17856332317")

    def test_e164_passes_through(self):
        self.assertEqual(lf.normalize_numbers("+17856332317", "phone number"), "+17856332317")


class ExtractFromTranscriptName(unittest.TestCase):

    def test_name_from_direct_ask(self):
        transcript = (
            "AI: May I have your first and last name?\n"
            "User: John Smith.\n"
        )
        self.assertEqual(lf._extract_from_transcript(transcript)["caller_name"], "John Smith")

    def test_volunteered_name_in_opening_line(self):
        transcript = (
            "AI: How can I help you today?\n"
            "User: My name is Thomas Iger. I have a question about trapping animals.\n"
            "AI: I can help with that.\n"
        )
        self.assertEqual(lf._extract_from_transcript(transcript)["caller_name"], "Thomas Iger")

    def test_this_is_pattern(self):
        transcript = "AI: How can I help?\nUser: Yes. This is James Redford.\n"
        self.assertEqual(lf._extract_from_transcript(transcript)["caller_name"], "James Redford")

    def test_direct_ask_wins_over_volunteered(self):
        transcript = (
            "User: This is Bob.\n"
            "AI: May I have your first and last name?\n"
            "User: Robert Jones.\n"
        )
        self.assertEqual(lf._extract_from_transcript(transcript)["caller_name"], "Robert Jones")

    def test_no_name_leaves_key_absent(self):
        transcript = "AI: How can I help?\nUser: I have ants.\n"
        self.assertNotIn("caller_name", lf._extract_from_transcript(transcript))


class ExtractFromTranscriptRating(unittest.TestCase):

    def test_spelled_out_rating(self):
        transcript = "AI: On a scale of one to five how concerned are you?\nUser: Three.\n"
        self.assertEqual(lf._extract_from_transcript(transcript)["concern_rating"], 3)

    def test_out_of_ten_is_scaled(self):
        transcript = "AI: On a scale of one to five how concerned are you?\nUser: 8 out of 10.\n"
        self.assertEqual(lf._extract_from_transcript(transcript)["concern_rating"], 4)


class PickRecordingUrl(unittest.TestCase):

    def test_presigned_stereo_beats_access_controlled_url(self):
        artifact = {"presignedStereoUrl": "https://p", "recordingUrl": "https://r2"}
        self.assertEqual(lf._pick_recording_url(artifact), "https://p")

    def test_presigned_mono_when_no_stereo(self):
        artifact = {"presignedMonoUrl": "https://m", "recordingUrl": "https://r2"}
        self.assertEqual(lf._pick_recording_url(artifact), "https://m")

    def test_top_level_recording_url_wins(self):
        artifact = {"recordingUrl": "https://a", "recording": {"url": "https://z"}}
        self.assertEqual(lf._pick_recording_url(artifact), "https://a")

    def test_mono_combined_before_legacy_url(self):
        artifact = {"recording": {"mono": {"combinedUrl": "https://m"}, "url": "https://z"}}
        self.assertEqual(lf._pick_recording_url(artifact), "https://m")

    def test_legacy_url_when_nothing_else(self):
        artifact = {"recording": {"url": "https://z"}}
        self.assertEqual(lf._pick_recording_url(artifact), "https://z")

    def test_mono_not_a_dict_does_not_crash(self):
        artifact = {"recording": {"mono": "unexpected", "url": "https://z"}}
        self.assertEqual(lf._pick_recording_url(artifact), "https://z")

    def test_no_recording_returns_empty(self):
        self.assertEqual(lf._pick_recording_url({}), "")


class BuildEmailBodyRecording(unittest.TestCase):

    def test_presigned_link_and_dashboard_link_both_present(self):
        body = lf.build_email_body({"recording_url": "https://p", "call_id": "abc"})
        self.assertIn("RECORDING\nhttps://p\nView in VAPI: https://dashboard.vapi.ai/calls/abc", body)

    def test_dashboard_link_alone_when_no_recording_url(self):
        body = lf.build_email_body({"call_id": "abc"})
        self.assertIn("RECORDING\nView in VAPI: https://dashboard.vapi.ai/calls/abc", body)

    def test_no_recording_section_when_neither(self):
        body = lf.build_email_body({})
        self.assertNotIn("RECORDING", body)


if __name__ == "__main__":
    unittest.main()
