# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl.html).

{
    "name": "IPLN Reconciliation by Cents",
    "summary": "Generate reconciliation models from PIX cents rules",
    "version": "18.0.1.0.0",
    "category": "Accounting",
    "author": "IPLN",
    "license": "AGPL-3",
    "depends": [
        "account_reconcile_analytic_tag",
    ],
    "data": [
        "security/ir.model.access.csv",
        "views/reconcile_rule_cents_views.xml",
    ],
    "installable": True,
    "application": False,
}

