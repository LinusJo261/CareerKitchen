"""Fictional direct ratings verify aggregation policies, not observed outcomes."""

import unittest
from copy import deepcopy

from scripts.joint_satisfaction_label import joint_satisfaction


class JointSatisfactionLabelTests(unittest.TestCase):
    def test_default_policy_uses_lower_ordinal_rating(self):
        self.assertEqual(joint_satisfaction(4, 1), {
            "employee_rating": 4,
            "manager_rating": 1,
            "joint_rating": 1.0,
            "joint_score": 25.0,
            "status": "OBSERVED_PAIRED",
            "aggregation": "minimum",
        })

    def test_one_high_rating_does_not_hide_a_low_rating_under_minimum(self):
        for employee, manager in ((0, 4), (4, 0)):
            with self.subTest(employee=employee, manager=manager):
                result = joint_satisfaction(employee, manager)
                self.assertEqual(result["joint_rating"], 0.0)
                self.assertEqual(result["joint_score"], 0.0)

    def test_policy_endpoints_and_agreement_preserve_rating(self):
        for rating in range(5):
            with self.subTest(rating=rating):
                result = joint_satisfaction(rating, rating)
                self.assertEqual(result["joint_rating"], float(rating))
                self.assertEqual(result["joint_score"], 25.0 * rating)

    def test_policy_treats_the_two_respondents_symmetrically(self):
        for employee in range(5):
            for manager in range(5):
                with self.subTest(employee=employee, manager=manager):
                    forward = joint_satisfaction(employee, manager)
                    reverse = joint_satisfaction(manager, employee)
                    self.assertEqual(forward["joint_rating"], reverse["joint_rating"])
                    self.assertEqual(forward["joint_score"], reverse["joint_score"])

    def test_increasing_either_rating_cannot_lower_joint_score(self):
        for employee in range(5):
            for manager in range(5):
                score = joint_satisfaction(employee, manager)["joint_score"]
                if employee < 4:
                    self.assertGreaterEqual(joint_satisfaction(employee + 1, manager)["joint_score"], score)
                if manager < 4:
                    self.assertGreaterEqual(joint_satisfaction(employee, manager + 1)["joint_score"], score)

    def test_joint_score_remains_between_both_individual_indices(self):
        for employee in range(5):
            for manager in range(5):
                result = joint_satisfaction(employee, manager)
                self.assertGreaterEqual(result["joint_score"], 25 * min(employee, manager))
                self.assertLessEqual(result["joint_score"], 25 * max(employee, manager))

    def test_missing_ratings_never_create_paired_labels(self):
        for employee, manager, status in (
            (None, None, "MISSING_BOTH"),
            (None, 4, "MISSING_EMPLOYEE"),
            (4, None, "MISSING_MANAGER"),
            (0, None, "MISSING_MANAGER"),
        ):
            with self.subTest(employee=employee, manager=manager):
                result = joint_satisfaction(employee, manager)
                self.assertEqual(result["status"], status)
                self.assertIsNone(result["joint_rating"])
                self.assertIsNone(result["joint_score"])
                self.assertEqual(result["employee_rating"], employee)
                self.assertEqual(result["manager_rating"], manager)
                self.assertEqual(result["aggregation"], "minimum")

    def test_whole_number_float_ratings_normalize_to_integer_indices(self):
        result = joint_satisfaction(2.0, 4.0)
        self.assertEqual(result["employee_rating"], 2)
        self.assertEqual(result["manager_rating"], 4)
        self.assertIs(type(result["employee_rating"]), int)
        self.assertIs(type(result["manager_rating"]), int)
        self.assertIs(type(result["joint_rating"]), float)
        self.assertIs(type(result["joint_score"]), float)

    def test_invalid_ratings_fail_for_either_party_even_if_other_is_missing(self):
        invalid = (
            True, False, -1, 5, -0.5, 0.5, 3.999999,
            float("nan"), float("inf"), float("-inf"),
            "4", "", [], {}, 10 ** 1000,
        )
        for value in invalid:
            for other in (None, 2):
                for position in ("employee", "manager"):
                    arguments = (value, other) if position == "employee" else (other, value)
                    with self.subTest(position=position, value=repr(value), other=other):
                        with self.assertRaises(ValueError):
                            joint_satisfaction(*arguments)

    def test_unknown_aggregation_fails_even_with_missing_ratings(self):
        for policy in ("equal_mean", "mean", "weighted", "MINIMUM", "", None, True, [], {}):
            with self.subTest(policy=policy), self.assertRaises(ValueError):
                joint_satisfaction(None, None, aggregation=policy)

    def test_input_values_are_unchanged_and_results_do_not_share_state(self):
        arguments = {"employee_rating": 3.0, "manager_rating": None, "aggregation": "minimum"}
        before = deepcopy(arguments)
        first = joint_satisfaction(**arguments)
        self.assertEqual(arguments, before)
        first["manager_rating"] = 4
        first["joint_score"] = 100
        second = joint_satisfaction(**arguments)
        self.assertIsNone(second["manager_rating"])
        self.assertIsNone(second["joint_score"])
        self.assertEqual(set(second), {
            "employee_rating", "manager_rating", "joint_rating", "joint_score", "status", "aggregation",
        })


if __name__ == "__main__":
    unittest.main()
