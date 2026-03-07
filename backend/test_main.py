import unittest

from backend.main import (
    ChatMessage,
    ChatRequest,
    MiamiExample,
    SESSIONS,
    SessionState,
    _is_ambiguous_interest_reference,
    _is_hostile_message,
    _is_out_of_scope_query,
    _is_soft_positive_confirmation,
    _is_social_message,
    _is_self_introduction,
    _is_small_talk,
    _normalize_candidate,
    _parse_llm_json,
    _rejects_suggested_options,
    _remaining_options,
    _should_try_typo_recovery,
    _small_talk_kind,
    choose_interest_label,
    chat,
    extract_interest_fallbacks,
)


class InterestExtractionTests(unittest.TestCase):
    def test_small_talk_is_not_treated_as_interest(self) -> None:
        self.assertTrue(_is_small_talk("Hi, how are you?"))
        self.assertTrue(_is_small_talk("what model are you?"))
        self.assertTrue(_is_self_introduction("Hi, I am Srinath"))
        self.assertEqual(_small_talk_kind("Hi, I am Srinath"), "introduction")
        self.assertEqual(_small_talk_kind("which ai model are you running"), "model")
        self.assertEqual(_small_talk_kind("what can you actually help me with here"), "help")

    def test_weather_question_is_out_of_scope(self) -> None:
        self.assertTrue(_is_out_of_scope_query("how is the weather today?"))
        self.assertTrue(_is_out_of_scope_query("is it going to rain later"))
        self.assertTrue(_is_out_of_scope_query("what's the temperature outside"))

    def test_social_and_hostile_turns_are_detected(self) -> None:
        self.assertTrue(_is_social_message("I love you"))
        self.assertTrue(_is_social_message("Bye"))
        self.assertTrue(_is_hostile_message("You are dumb"))
        self.assertTrue(_is_hostile_message("Are you a parrot?"))

    def test_movies_and_arcades_are_both_detected(self) -> None:
        candidates = extract_interest_fallbacks("we love going to movies and arcades", [])
        labels = [item["label"] for item in candidates]
        self.assertIn("movies", labels)
        self.assertIn("arcades and gaming", labels)

    def test_racket_sports_detected_from_padel_and_tennis(self) -> None:
        candidates = extract_interest_fallbacks("I love playing padel and tennis", [])
        labels = [item["label"] for item in candidates]
        self.assertIn("racket sports", labels)

    def test_outdoor_activities_detected_from_parks_and_hikes(self) -> None:
        candidates = extract_interest_fallbacks("I take long walks with my dog at parks and hikes with my family", [])
        labels = [item["label"] for item in candidates]
        self.assertIn("outdoor activities", labels)

    def test_waterrides_maps_to_water_parks(self) -> None:
        candidates = extract_interest_fallbacks("i need to play waterrides", [])
        self.assertEqual(candidates[0]["label"], "water parks")

    def test_specific_cuisine_is_preserved_in_fallbacks(self) -> None:
        candidates = extract_interest_fallbacks("what are the best places for indian food in town", [])
        self.assertEqual(candidates[0]["label"], "indian food")
        self.assertEqual(candidates[0]["search_query"], "indian restaurants")

    def test_specific_cuisine_query_upgrades_generic_food_label(self) -> None:
        candidate = _normalize_candidate("food", "indian restaurants")
        self.assertEqual(candidate["label"], "indian food")
        self.assertEqual(candidate["search_query"], "indian restaurants")

    def test_exact_supported_food_category_does_not_collapse(self) -> None:
        self.assertEqual(choose_interest_label("mexican food"), "mexican food")

    def test_recent_suggestions_are_not_repeated_first(self) -> None:
        messages = [
            ChatMessage(role="assistant", content="How about food or live music?"),
            ChatMessage(role="assistant", content="Maybe rooftop bars or art galleries?"),
        ]
        opts = _remaining_options([], messages, limit=4).split(", ")
        self.assertNotIn("food", opts)
        self.assertNotIn("live music", opts)
        self.assertNotIn("rooftop bars", opts)
        self.assertNotIn("art galleries", opts)

    def test_recent_rejections_are_removed_from_suggestions(self) -> None:
        messages = [
            ChatMessage(role="user", content="I dont want mexican food"),
            ChatMessage(role="assistant", content="Got it, tell me what you do want."),
        ]
        opts = _remaining_options(["water sports"], messages, limit=5).split(", ")
        self.assertNotIn("mexican food", opts)

    def test_opening_suggestions_do_not_default_to_mexican_food(self) -> None:
        messages = [ChatMessage(role="user", content="hi")]
        opts = _remaining_options([], messages, limit=5).split(", ")
        self.assertNotIn("mexican food", opts)
        self.assertTrue(any(option in opts for option in ["movies", "outdoor activities", "live music", "art galleries", "shopping", "coffee shops"]))

    def test_parse_llm_json_with_leading_text(self) -> None:
        raw = (
            "Got it. Here are some spots for that.\n\n"
            '{"assistant_message":"Nice, here are some spots for that.","interest_candidates":'
            '[{"label":"nightlife","search_query":"nightclubs and bars"}]}'
        )
        parsed = _parse_llm_json(raw)
        self.assertEqual(parsed["assistant_message"], "Nice, here are some spots for that.")
        self.assertEqual(parsed["interest_candidates"][0]["label"], "nightlife")

    def test_generic_rejection_of_suggested_options_is_detected(self) -> None:
        self.assertTrue(_rejects_suggested_options("i dont like these actually"))
        self.assertTrue(_rejects_suggested_options("none of those options"))
        self.assertTrue(_rejects_suggested_options("can you give me something else"))
        self.assertFalse(_rejects_suggested_options("i dont like brunch"))

    def test_typo_recovery_trigger_handles_merged_words(self) -> None:
        self.assertTrue(_should_try_typo_recovery("i need waterrides"))
        self.assertTrue(_should_try_typo_recovery("pedal courts"))
        self.assertFalse(_should_try_typo_recovery("i like live music"))

    def test_soft_positive_confirmation_is_detected(self) -> None:
        self.assertTrue(_is_soft_positive_confirmation("i like to checkout these places"))
        self.assertTrue(_is_soft_positive_confirmation("these look good"))
        self.assertFalse(_is_soft_positive_confirmation("i like arcades and movies"))

    def test_ambiguous_interest_reference_is_detected(self) -> None:
        self.assertTrue(_is_ambiguous_interest_reference("i like these as well"))
        self.assertTrue(_is_ambiguous_interest_reference("i want to checkout these"))
        self.assertFalse(_is_ambiguous_interest_reference("i like movies and arcades"))

    def test_soft_positive_confirmation_keeps_cards_visible(self) -> None:
        session_id = "soft-confirm-test"
        state = SessionState()
        state.interests = ["movies"]
        state.awaiting_confirmation = True
        state.last_examples = [
            MiamiExample(
                name="Test Cinema",
                neighborhood="Brickell",
                description="Movie theater",
                hours="Open",
            )
        ]
        SESSIONS[session_id] = state
        try:
            response = chat(ChatRequest(session_id=session_id, message="i like to checkout these places"))
            self.assertEqual(len(response.examples), 1)
            self.assertEqual(response.examples[0].name, "Test Cinema")
            self.assertIn("tap Yes", response.assistant_message)
            self.assertEqual(response.interests, ["movies"])
        finally:
            SESSIONS.pop(session_id, None)

    def test_ambiguous_reference_without_cards_asks_for_one_interest(self) -> None:
        session_id = "ambiguous-reference-test"
        state = SessionState()
        state.interests = []
        state.awaiting_confirmation = False
        SESSIONS[session_id] = state
        try:
            response = chat(ChatRequest(session_id=session_id, message="i like these as well"))
            self.assertEqual(response.examples, [])
            self.assertIn("one", response.assistant_message.lower())
            self.assertIn("interest", response.assistant_message.lower())
        finally:
            SESSIONS.pop(session_id, None)


if __name__ == "__main__":
    unittest.main()
