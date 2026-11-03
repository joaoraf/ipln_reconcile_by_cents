# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl.html).

import re

from odoo import Command
from odoo.exceptions import ValidationError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged("post_install", "-at_install")
class TestReconcileRuleCents(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.account = cls.env["account.account"].create({
            "name": "Cents rule counterpart",
            "code": "999991",
            "account_type": "income_other",
            "company_ids": [Command.link(cls.env.company.id)],
        })
        cls.plan = cls.env["account.analytic.plan"].create({
            "name": "Cents rule plan",
        })
        cls.analytic_account = cls.env["account.analytic.account"].create({
            "name": "Cents rule analytic account",
            "plan_id": cls.plan.id,
            "company_id": cls.env.company.id,
        })
        cls.analytic_tag = cls.env["account.analytic.tag"].create({
            "name": "Cents rule analytic tag",
            "company_id": cls.env.company.id,
            "account_analytic_id": cls.analytic_account.id,
        })

    def _create_rule(self, **extra_values):
        values = {
            "name": "PIX cents test",
            "company_id": self.env.company.id,
            "sequence": 42,
            "cents": 7,
            "counterpart_account_code": self.account.code,
            "maximum_amount": 200,
            "analytic_distribution": {str(self.analytic_account.id): 100},
            "analytic_tag_ids": [Command.set(self.analytic_tag.ids)],
        }
        values.update(extra_values)
        return self.env["ipln.reconcile.rule.cents"].create(values)

    def test_create_and_link(self):
        rule = self._create_rule()
        model = rule.reconcile_model_id

        self.assertTrue(model)
        self.assertEqual(model.source_cents_rule_id, rule)
        self.assertEqual(rule.counterpart_account_id, self.account)
        self.assertEqual(model.name, rule.name)
        self.assertEqual(model.company_id, rule.company_id)
        self.assertEqual(model.sequence, 42)
        self.assertEqual(
            model.match_label_param,
            r".*(?:(?:pix|transferência)[ -]*recebid[oa]|"
            r"transferência periódica).*amount:.*\.07",
        )
        self.assertEqual(model.match_amount, "lower")
        self.assertEqual(model.match_amount_max, 200)
        self.assertEqual(model.line_ids.account_id, self.account)
        self.assertEqual(
            model.line_ids.analytic_distribution,
            {str(self.analytic_account.id): 100.0},
        )
        self.assertEqual(model.line_ids.analytic_tag_ids, self.analytic_tag)

    def test_write_archive_restore_and_catch_all(self):
        rule = self._create_rule()
        model = rule.reconcile_model_id

        rule.write({
            "name": "Catch-all PIX",
            "cents": None,
            "maximum_amount": 0,
            "active": False,
        })

        self.assertEqual(rule.cents, None)
        self.assertEqual(model.name, "Catch-all PIX")
        self.assertEqual(
            model.match_label_param,
            r".*(?:(?:pix|transferência)[ -]*recebid[oa]|"
            r"transferência periódica).*amount:.*",
        )
        self.assertFalse(model.match_amount)
        self.assertFalse(model.active)

        rule.active = True
        self.assertTrue(model.active)

    def test_zero_cents_is_not_the_catch_all_value(self):
        rule = self._create_rule(cents=0)

        self.assertEqual(rule.cents, 0)
        self.assertEqual(
            rule.reconcile_model_id.match_label_param,
            r".*(?:(?:pix|transferência)[ -]*recebid[oa]|"
            r"transferência periódica).*amount:.*\.00",
        )

    def test_generated_pattern_matches_received_pix_and_transfer(self):
        rule = self._create_rule(cents=7)
        model = rule.reconcile_model_id

        matching_labels = [
            "Pix - Recebido 123 : PESSOA Amount:20.07",
            "Pix-Recebido QR Code 123 : PESSOA Amount:20.07",
            "Transferência recebida 123 : PESSOA Amount:20.07",
            "Transferência Periódica 123 : PESSOA Amount:20.07",
        ]
        for label in matching_labels:
            self.assertTrue(
                re.match(model.match_label_param.lower(), label.lower()),
                label,
            )

    def test_generated_pattern_rejects_other_transfers(self):
        rule = self._create_rule(cents=7)
        label = "Transferência Agendada 123 : PESSOA Amount:20.07"

        pattern = rule.reconcile_model_id.match_label_param.lower()
        self.assertFalse(
            re.match(pattern, label.lower())
        )

    def test_link_recreates_removed_model(self):
        rule = self._create_rule()
        old_model = rule.reconcile_model_id
        old_model.unlink()
        rule.invalidate_recordset(["reconcile_model_id"])

        self.assertFalse(rule.reconcile_model_id)
        model = rule.link()

        self.assertTrue(model)
        self.assertNotEqual(model, old_model)
        self.assertEqual(model.source_cents_rule_id, rule)

    def test_unlink_removes_generated_model(self):
        rule = self._create_rule()
        model = rule.reconcile_model_id

        rule.unlink()

        self.assertFalse(model.exists())

    def test_rejects_cents_outside_valid_range(self):
        with self.assertRaises(ValidationError):
            self._create_rule(cents=100)

