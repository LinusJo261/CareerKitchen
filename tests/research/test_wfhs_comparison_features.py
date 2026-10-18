"""Fictional baseline snapshots verify feature calculations, not prediction quality."""

import math
import unittest
from fractions import Fraction

from scripts.wfhs_comparison_features import (
    ADDITIONAL_CONDITION_FEATURE_NAMES,
    BASE_FEATURE_NAMES,
    CONTEXT_FEATURE_NAMES,
    EXPANDED_VARIANTS,
    INTERACTION_FEATURE_NAMES,
    VARIANTS,
    feature_bounds,
    feature_names,
    feature_variant,
)


def baseline(**changes):
    return {
        "control_over_work_hours": 2,
        "family_supportive_supervisor": 4,
        "decision_authority": 3,
        "psychological_job_demands": 4,
        "hours_worked_last_week": 45,
        "hours_expected_by_manager": 40,
        **changes,
    }


def context(**changes):
    return baseline(
        work_to_family_conflict=2,
        emotional_burnout=6.5,
        work_family_climate=4,
        baseline_satisfaction=11 / 3,
        **changes,
    )


class WFHSComparisonFeatureTests(unittest.TestCase):
    def test_baseline_has_exact_six_inputs_and_returns_independent_mapping(self):
        source = baseline()
        result = feature_variant(source, "baseline")
        self.assertEqual(result, source)
        self.assertEqual(tuple(result), BASE_FEATURE_NAMES)
        self.assertFalse(set(result) & set(INTERACTION_FEATURE_NAMES))
        self.assertIsNot(result, source)
        result["decision_authority"] = 5
        self.assertEqual(source["decision_authority"], 3)

    def test_interactions_use_documented_math_and_preserve_baseline(self):
        source = baseline()
        unchanged = dict(source)
        result = feature_variant(source, "interactions")
        self.assertEqual(tuple(result), BASE_FEATURE_NAMES + INTERACTION_FEATURE_NAMES)
        self.assertEqual({name: result[name] for name in BASE_FEATURE_NAMES}, source)
        self.assertEqual(result["hours_gap"], 5)
        self.assertEqual(result["absolute_hours_gap"], 5)
        self.assertAlmostEqual(result["demands_by_low_control"], 0.75 * 0.75)
        self.assertAlmostEqual(result["demands_by_low_support"], 0.75 * 0.25)
        self.assertEqual(source, unchanged)

    def test_negative_gap_keeps_direction_alongside_absolute_magnitude(self):
        result = feature_variant(baseline(hours_worked_last_week=32), "interactions")
        self.assertEqual(result["hours_gap"], -8)
        self.assertEqual(result["absolute_hours_gap"], 8)

    def test_zero_expected_hours_and_zero_actual_hours_need_no_division(self):
        for actual, expected, gap in ((45, 0, 45), (0, 40, -40), (0, 0, 0)):
            with self.subTest(actual=actual, expected=expected):
                result = feature_variant(
                    baseline(hours_worked_last_week=actual, hours_expected_by_manager=expected),
                    "interactions",
                )
                self.assertEqual(result["hours_gap"], gap)
                self.assertEqual(result["absolute_hours_gap"], abs(gap))

    def test_missing_operand_propagates_only_to_dependent_interactions(self):
        for missing in BASE_FEATURE_NAMES:
            with self.subTest(missing=missing):
                result = feature_variant(baseline(**{missing: None}), "interactions")
                self.assertIsNone(result[missing])
                for interaction in ("hours_gap", "absolute_hours_gap"):
                    if missing in BASE_FEATURE_NAMES[-2:]:
                        self.assertIsNone(result[interaction])
                    else:
                        self.assertIsNotNone(result[interaction])
                if missing in {"psychological_job_demands", "control_over_work_hours"}:
                    self.assertIsNone(result["demands_by_low_control"])
                else:
                    self.assertIsNotNone(result["demands_by_low_control"])
                if missing in {"psychological_job_demands", "family_supportive_supervisor"}:
                    self.assertIsNone(result["demands_by_low_support"])
                else:
                    self.assertIsNotNone(result["demands_by_low_support"])
        unknown = dict.fromkeys(BASE_FEATURE_NAMES)
        self.assertTrue(all(value is None for value in feature_variant(unknown, "interactions").values()))

    def test_endpoint_values_keep_signed_hours_and_bounded_interaction(self):
        for actual, expected in ((168, 0), (0, 168), (168, 168)):
            for demands, control in ((1, 1), (1, 5), (5, 1), (5, 5)):
                with self.subTest(actual=actual, expected=expected, demands=demands, control=control):
                    result = feature_variant(
                        baseline(
                            hours_worked_last_week=actual,
                            hours_expected_by_manager=expected,
                            psychological_job_demands=demands,
                            control_over_work_hours=control,
                        ),
                        "interactions",
                    )
                    self.assertEqual(result["hours_gap"], actual - expected)
                    self.assertEqual(
                        result["demands_by_low_control"], 1 if (demands, control) == (5, 1) else 0
                    )
                    self.assertTrue(all(math.isfinite(value) for value in result.values()))

    def test_real_numbers_are_accepted_without_rounding(self):
        result = feature_variant(baseline(psychological_job_demands=Fraction(7, 3)), "interactions")
        self.assertAlmostEqual(result["psychological_job_demands"], 7 / 3)
        self.assertAlmostEqual(result["demands_by_low_control"], 0.25)
        self.assertAlmostEqual(result["demands_by_low_support"], 1 / 12)

    def test_low_support_interaction_endpoints_do_not_depend_on_control(self):
        for demands, support in ((1, 1), (1, 5), (5, 1), (5, 5)):
            with self.subTest(demands=demands, support=support):
                result = feature_variant(
                    baseline(psychological_job_demands=demands, family_supportive_supervisor=support),
                    "interactions",
                )
                self.assertEqual(result["demands_by_low_support"], 1 if (demands, support) == (5, 1) else 0)

    def test_invalid_values_are_rejected_for_every_feature_and_variant(self):
        for name in BASE_FEATURE_NAMES:
            low, high = (0, 168) if name in BASE_FEATURE_NAMES[-2:] else (1, 5)
            for invalid in (
                True,
                False,
                "3",
                [],
                {},
                math.nan,
                math.inf,
                -math.inf,
                1e308,
                10**1000,
                low - 0.01,
                high + 0.01,
            ):
                for variant in VARIANTS:
                    with self.subTest(name=name, invalid=repr(invalid), variant=variant):
                        with self.assertRaises(ValueError):
                            feature_variant(baseline(**{name: invalid}), variant)

    def test_source_aliases_missing_fields_ids_targets_and_later_values_are_rejected(self):
        alias = baseline()
        alias["SCWM_CWH"] = alias.pop("control_over_work_hours")
        missing = baseline()
        del missing["hours_expected_by_manager"]
        bad = [None, [], alias, missing]
        for extra in (
            "person_id",
            "followup_satisfaction",
            "baseline_satisfaction",
            "outcome_wave",
            "hours_gap",
            "followup_control_over_work_hours",
        ):
            bad.append(baseline(**{extra: 3}))
        for features in bad:
            for variant in VARIANTS:
                with self.subTest(features=features, variant=variant):
                    with self.assertRaises(ValueError):
                        feature_variant(features, variant)

    def test_unknown_variants_fail_instead_of_selecting_default(self):
        for variant in ("", "Baseline", "unknown", None, [], {}):
            with self.subTest(variant=variant):
                with self.assertRaises(ValueError):
                    feature_variant(baseline(), variant)

    def test_complete_context_selects_exact_ordered_feature_ablations(self):
        source = context()
        self.assertEqual(tuple(source), CONTEXT_FEATURE_NAMES)
        self.assertEqual(VARIANTS, ("baseline", "interactions"))
        expected = {
            "baseline": BASE_FEATURE_NAMES,
            "interactions": BASE_FEATURE_NAMES + INTERACTION_FEATURE_NAMES,
            "expanded": BASE_FEATURE_NAMES + ADDITIONAL_CONDITION_FEATURE_NAMES,
            "baseline_with_satisfaction": BASE_FEATURE_NAMES + ("baseline_satisfaction",),
            "expanded_with_satisfaction": CONTEXT_FEATURE_NAMES,
        }
        for variant, names in expected.items():
            with self.subTest(variant=variant):
                result = feature_variant(source, variant)
                self.assertEqual(tuple(result), names)
                self.assertEqual(feature_names(variant), list(names))
                self.assertIsNot(result, source)
                if "baseline_satisfaction" in names:
                    self.assertAlmostEqual(result["baseline_satisfaction"], 11 / 3)
        for variant in VARIANTS:
            self.assertEqual(feature_variant(source, variant), feature_variant(baseline(), variant))

    def test_unused_context_fields_cannot_change_an_ablation_or_hide_invalid_values(self):
        source = context()
        changed = dict(
            source,
            work_to_family_conflict=5,
            emotional_burnout=1,
            work_family_climate=1,
            baseline_satisfaction=1,
        )
        for variant in VARIANTS:
            self.assertEqual(feature_variant(source, variant), feature_variant(changed, variant))
        self.assertEqual(
            feature_variant(source, "expanded"),
            feature_variant(dict(source, baseline_satisfaction=1), "expanded"),
        )
        self.assertEqual(
            feature_variant(source, "baseline_with_satisfaction"),
            feature_variant(
                dict(changed, baseline_satisfaction=source["baseline_satisfaction"]),
                "baseline_with_satisfaction",
            ),
        )
        with self.assertRaises(ValueError):
            feature_variant(dict(source, emotional_burnout=8), "baseline")

    def test_new_context_domains_and_missing_values_apply_to_every_variant(self):
        for name in ADDITIONAL_CONDITION_FEATURE_NAMES + ("baseline_satisfaction",):
            low, high = feature_bounds(name)
            for variant in VARIANTS + EXPANDED_VARIANTS:
                for valid in (None, low, high, (low + high) / 2):
                    source = dict(context(), **{name: valid})
                    result = feature_variant(source, variant)
                    if name in feature_names(variant):
                        self.assertEqual(result[name], valid)
                for invalid in (True, "3", math.nan, math.inf, low - 0.01, high + 0.01):
                    with (
                        self.subTest(name=name, variant=variant, invalid=invalid),
                        self.assertRaises(ValueError),
                    ):
                        feature_variant(dict(context(), **{name: invalid}), variant)
        self.assertEqual(feature_bounds("emotional_burnout"), (1, 7))
        with self.assertRaises(ValueError):
            feature_bounds("followup_satisfaction")

    def test_satisfaction_only_uses_one_baseline_response_and_validates_the_full_context(self):
        source = context()
        before = dict(source)
        self.assertEqual(feature_names("satisfaction_only"), ["baseline_satisfaction"])
        self.assertEqual(feature_variant(source, "satisfaction_only"), {"baseline_satisfaction": 11 / 3})
        changed = {name: None for name in CONTEXT_FEATURE_NAMES}
        changed["baseline_satisfaction"] = source["baseline_satisfaction"]
        self.assertEqual(
            feature_variant(source, "satisfaction_only"), feature_variant(changed, "satisfaction_only")
        )
        self.assertEqual(source, before)
        self.assertEqual(
            feature_variant(dict(source, baseline_satisfaction=None), "satisfaction_only"),
            {"baseline_satisfaction": None},
        )
        for bad in (
            baseline(),
            {"baseline_satisfaction": 3},
            dict(source, followup_satisfaction=4),
            dict(source, baseline_satisfaction=6),
            dict(source, emotional_burnout=8),
        ):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                feature_variant(bad, "satisfaction_only")

    def test_expanded_variants_require_full_context_and_reject_outcomes(self):
        partial = context()
        del partial["baseline_satisfaction"]
        for variant in VARIANTS + EXPANDED_VARIANTS:
            for source in (
                partial,
                dict(context(), followup_satisfaction=4),
                dict(context(), outcome_wave=3),
            ):
                with self.subTest(variant=variant, keys=list(source)), self.assertRaises(ValueError):
                    feature_variant(source, variant)
        for variant in EXPANDED_VARIANTS:
            with self.subTest(variant=variant), self.assertRaises(ValueError):
                feature_variant(baseline(), variant)


if __name__ == "__main__":
    unittest.main()
