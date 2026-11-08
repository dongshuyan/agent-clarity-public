import unittest
from evals.run import make_prompt, validate_answers


class EvaluationTests(unittest.TestCase):
    def test_writer_does_not_see_gold_answers_or_split(self):
        prompt = make_prompt([{'id': 'a', 'prompt': 'Explain', 'source': 'Source text',
                               'split': 'holdout', 'required_facts': ['SECRET GOLD'],
                               'questions': [{'answer': 'HIDDEN ANSWER'}]}])
        self.assertIn('Source text', prompt)
        self.assertNotIn('SECRET GOLD', prompt)
        self.assertNotIn('HIDDEN ANSWER', prompt)
        self.assertNotIn('holdout', prompt)

    def test_missing_duplicated_or_empty_outputs_fail(self):
        for answers in [[], [{'id': 'a', 'text': ''}],
                        [{'id': 'a', 'text': 'x'}, {'id': 'a', 'text': 'y'}],
                        [{'id': 'wrong', 'text': 'x'}]]:
            with self.subTest(answers=answers), self.assertRaises(ValueError):
                validate_answers({'answers': answers}, ['a'])

    def test_complete_output_is_accepted_without_scoring_style(self):
        value = {'answers': [{'id': 'a', 'text': 'A useful answer'}]}
        self.assertEqual(validate_answers(value, ['a']), value)


if __name__ == '__main__':
    unittest.main()
