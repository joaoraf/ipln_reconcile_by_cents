# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl.html).

from odoo import Command, _, api, fields, models
from odoo.exceptions import ValidationError


class NullableInteger(fields.Integer):
    """An integer field that keeps ``NULL`` distinct from zero."""

    def convert_to_column(self, value, record, values=None, validate=True):
        if value is None or value is False:
            return None
        return int(value)

    def convert_to_cache(self, value, record, validate=True):
        if value is None or value is False:
            return None
        return int(value)

    def convert_to_record(self, value, record):
        return value


class IplnReconcileRuleCents(models.Model):
    _name = "ipln.reconcile.rule.cents"
    _inherit = "analytic.mixin"
    _description = "Reconciliation Rule by Cents"
    _order = "sequence, id"
    _check_company_auto = True

    name = fields.Char(required=True, translate=True)
    company_id = fields.Many2one(
        comodel_name="res.company",
        required=True,
        default=lambda self: self.env.company,
        index=True,
    )
    active = fields.Boolean(default=True)
    sequence = fields.Integer(default=10)
    cents = NullableInteger(
        help="Cent value from 0 to 99. Leave empty to match every cent value.",
    )
    counterpart_account_id = fields.Many2one(
        comodel_name="account.account",
        string="Counterpart Account",
        required=True,
        ondelete="restrict",
        check_company=True,
        domain="[('company_ids', 'in', company_id)]",
    )
    counterpart_account_code = fields.Char(
        string="Counterpart Account Code",
        required=True,
        help="Stable account code used by configuration data.",
    )
    currency_id = fields.Many2one(
        related="company_id.currency_id",
    )
    maximum_amount = fields.Monetary(
        help="Leave zero to apply the rule without an amount limit.",
    )
    analytic_tag_ids = fields.Many2many(
        comodel_name="account.analytic.tag",
        relation="ipln_reconcile_rule_cents_analytic_tag_rel",
        column1="rule_id",
        column2="tag_id",
        string="Analytic Tags",
        check_company=True,
    )
    reconcile_model_id = fields.Many2one(
        comodel_name="account.reconcile.model",
        string="Generated Reconciliation Model",
        readonly=True,
        copy=False,
        ondelete="set null",
    )

    @api.constrains("cents")
    def _check_cents(self):
        for rule in self:
            if rule.cents is not None and not 0 <= rule.cents <= 99:
                raise ValidationError(_("Cents must be between 0 and 99."))

    @api.constrains("maximum_amount")
    def _check_maximum_amount(self):
        for rule in self:
            if rule.maximum_amount < 0:
                raise ValidationError(_("Maximum amount cannot be negative."))

    @api.onchange("counterpart_account_id")
    def _onchange_counterpart_account_id(self):
        if self.counterpart_account_id:
            self.counterpart_account_code = self.counterpart_account_id.code

    @api.model
    def _account_from_code(self, company_id, account_code):
        accounts = self.env["account.account"].with_company(company_id).search([
            ("company_ids", "in", company_id),
            ("code", "=", account_code),
        ], limit=2)
        if len(accounts) != 1:
            raise ValidationError(
                _(
                    "Expected exactly one account with code %(code)s for "
                    "%(company)s; found %(count)s.",
                    code=account_code,
                    company=self.env["res.company"].browse(company_id).display_name,
                    count=len(accounts),
                )
            )
        return accounts

    @api.model
    def _normalize_account_values(self, values, company_id=None):
        values = dict(values)
        company_id = values.get("company_id", company_id or self.env.company.id)
        if "counterpart_account_id" in values and values["counterpart_account_id"]:
            account = self.env["account.account"].browse(
                values["counterpart_account_id"]
            )
            values["counterpart_account_code"] = account.code
        elif values.get("counterpart_account_code"):
            account = self._account_from_code(
                company_id,
                values["counterpart_account_code"],
            )
            values["counterpart_account_id"] = account.id
        return values

    @api.model_create_multi
    def create(self, values_list):
        values_list = [
            self._normalize_account_values(values)
            for values in values_list
        ]
        rules = super().create(values_list)
        rules.link()
        return rules

    def write(self, values):
        if self.env.context.get("skip_cents_rule_sync"):
            return super().write(values)

        if {
            "company_id",
            "counterpart_account_id",
            "counterpart_account_code",
        } & values.keys():
            for rule in self:
                values_to_write = dict(values)
                if (
                    "company_id" in values_to_write
                    and "counterpart_account_id" not in values_to_write
                    and "counterpart_account_code" not in values_to_write
                ):
                    values_to_write["counterpart_account_code"] = (
                        rule.counterpart_account_code
                    )
                normalized_values = self._normalize_account_values(
                    values_to_write,
                    company_id=rule.company_id.id,
                )
                super(IplnReconcileRuleCents, rule).write(normalized_values)
            result = True
        else:
            result = super().write(values)
        self.link()
        return result

    def unlink(self):
        reconcile_models = self.reconcile_model_id
        result = super().unlink()
        reconcile_models.unlink()
        return result

    def _prepare_reconcile_model_line_values(self):
        self.ensure_one()
        return {
            "sequence": 10,
            "account_id": self.counterpart_account_id.id,
            "amount_type": "percentage",
            "amount_string": "100",
            "force_tax_included": False,
            "analytic_distribution": self.analytic_distribution or False,
            "analytic_tag_ids": [Command.set(self.analytic_tag_ids.ids)],
        }

    def _prepare_reconcile_model_values(self, update=False):
        self.ensure_one()
        # account_reconcile_model_oca lowercases both this expression and the
        # statement label before matching.  Keep this in sync with the
        # received-payment expression in transform_expectation.py.
        label_pattern = (
                r".*(?:(?:pix|transferência)[ -]*(?:recebid[oa]|agendad[oa]|periódic[oa])).*amount:.*"
        )
        if self.cents is not None:
            label_pattern += rf"\.{self.cents:02d}"
        bank_journals = self.env["account.journal"].search([
            ("company_id", "=", self.company_id.id),
            ("type", "=", "bank"),
        ])
        line_commands = [
            Command.create(self._prepare_reconcile_model_line_values()),
        ]
        if update:
            line_commands.insert(0, Command.clear())
        values = {
            "name": self.name,
            "company_id": self.company_id.id,
            "active": self.active,
            "sequence": self.sequence,
            "rule_type": "writeoff_suggestion",
            "unique_matching": False,
            "auto_reconcile": True,
            "to_check": False,
            "matching_order": "old_first",
            "counterpart_type": "general",
            "match_text_location_label": True,
            "match_text_location_note": False,
            "match_text_location_reference": False,
            "match_journal_ids": [Command.set(bank_journals.ids)],
            "match_nature": "amount_received",
            "match_label": "match_regex",
            "match_label_param": label_pattern,
            "match_same_currency": True,
            "allow_payment_tolerance": True,
            "payment_tolerance_type": "percentage",
            "payment_tolerance_param": 0,
            "match_partner": False,
            "decimal_separator": ",",
            "match_amount": "lower" if self.maximum_amount else False,
            "match_amount_min": 0,
            "match_amount_max": self.maximum_amount or 0,
            "line_ids": line_commands,
        }
        return values

    def link(self):
        """Create or synchronize the standard reconciliation model."""
        reconciliation_model = self.env["account.reconcile.model"]
        for rule in self:
            model = rule.reconcile_model_id.exists()
            if not model:
                model = reconciliation_model.search([
                    ("source_cents_rule_id", "=", rule.id),
                ], limit=1)
            values = rule._prepare_reconcile_model_values(update=bool(model))
            if model:
                model.write(values)
                if rule.reconcile_model_id != model:
                    rule.with_context(skip_cents_rule_sync=True).write({
                        "reconcile_model_id": model.id,
                    })
            else:
                model = reconciliation_model.create({
                    **values,
                    "source_cents_rule_id": rule.id,
                })
                rule.with_context(skip_cents_rule_sync=True).write({
                    "reconcile_model_id": model.id,
                })
        return self.reconcile_model_id

    def action_open_reconcile_model(self):
        self.ensure_one()
        self.link()
        return {
            "type": "ir.actions.act_window",
            "name": _("Reconciliation Model"),
            "res_model": "account.reconcile.model",
            "res_id": self.reconcile_model_id.id,
            "view_mode": "form",
            "target": "current",
        }


class AccountReconcileModel(models.Model):
    _inherit = "account.reconcile.model"

    source_cents_rule_id = fields.Many2one(
        comodel_name="ipln.reconcile.rule.cents",
        string="Source Cents Rule",
        readonly=True,
        copy=False,
        ondelete="set null",
        index=True,
    )

    _sql_constraints = [
        (
            "source_cents_rule_unique",
            "unique(source_cents_rule_id)",
            "A cents rule can only be linked to one reconciliation model.",
        ),
    ]

