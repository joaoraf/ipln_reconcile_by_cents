# Defining reconciliation-by-cents rules in code

Rules can be installed with an accounting chart by returning
`ipln.reconcile.rule.cents` records from an Odoo chart-template method. The
IPLN configuration keeps the declarations in `PIX_RECONCILE_RULES` in
`ipln_account/models/template_ipln.py`.

Creating the source rule is sufficient. Its `create()` method resolves the
counterpart account and immediately creates the corresponding standard
`account.reconcile.model`. Later writes, archiving, restoration, and deletion
of the source rule are propagated to that generated model.

## Basic declaration

Add a dictionary to `PIX_RECONCILE_RULES`:

```python
PIX_RECONCILE_RULES = [
    {
        "name": "PIX Barnabé",
        "sequence": 10,
        "cents": 7,
        "counterpart_account_code": "4.02.03",
        "maximum_amount": 200,
    },
]
```

This declaration generates a reconciliation model that:

- searches the transaction label with the regular expression
  `.*(?:(?:pix|transferência)[ -]*recebid[oa]|transferência periódica).*amount:.*\.07`;
- applies only to received amounts lower than the configured maximum; and
- creates a 100% counterpart line in account `4.02.03`.

The common expression recognizes received PIX descriptions (including the
forms with a hyphen), `Transferência recebida`, and `Transferência Periódica`
descriptions. Matching is case-insensitive because the OCA reconciliation
engine lowercases the expression and the transaction label before applying it.

To add another rule, add another dictionary. Do not add an
`account.reconcile.model` declaration for the same rule.

## Fields

### `name`

Required string. It is used as the name of both the source rule and the
generated reconciliation model.

The IPLN chart currently derives the rule's external identifier from this
name. Treat a name already deployed through the chart as stable: renaming it
in code can cause a new external identifier to be created instead of updating
the existing record.

### `company_id`

Required by the database model, but it must normally be omitted from
`PIX_RECONCILE_RULES`. `_get_ipln_reconcile_rules_by_cents()` supplies the
company currently receiving the chart.

When creating a rule directly through the ORM, pass the target company ID.
If omitted outside chart configuration, it defaults to the current company.

### `active`

Optional boolean; defaults to `True`. An inactive rule remains in the
database, but its generated reconciliation model is inactive as well.

Use `False` when a rule should be installed in an archived state:

```python
"active": False,
```

### `sequence`

Optional integer; defaults to `10`. Lower values give the generated
reconciliation model higher priority relative to models with larger sequence
values.

Use distinct values when two rules could match the same bank transaction,
especially when combining specific-cent rules with a catch-all rule.

### `cents`

Integer from `0` through `99`, or `None` for a catch-all received-payment
rule. The key is required in `PIX_RECONCILE_RULES`.

Values are formatted with two digits. For example:

```python
"cents": 0,   # adds \.00 to the regular expression
"cents": 7,   # adds \.07 to the regular expression
"cents": 42,  # adds \.42 to the regular expression
```

Zero is a real cents value and is different from `None`:

```python
{
    "name": "Other received payments",
    "sequence": 100,
    "cents": None,
    "counterpart_account_code": "4.02.99",
}
```

The catch-all case still requires the transaction to match the common
received PIX or received-transfer label expression; it only omits the cents
suffix. Give it a larger sequence than the specific rules so it is considered
afterwards.

### `counterpart_account_code`

Required string for declarations in code. It is the stable accounting code
used to find `counterpart_account_id` in the target company. Exactly one
account with that code must exist for the company, otherwise chart loading
raises a validation error.

Prefer this field over a numeric account ID in configuration code because
database IDs differ between installations.

### `counterpart_account_id`

Required relation on the persisted rule, but normally omitted from code
declarations. It is resolved automatically from
`counterpart_account_code`.

For direct ORM creation, either field may be supplied. If an account ID is
provided, its current account code is copied to
`counterpart_account_code`.

### `maximum_amount`

Optional non-negative monetary value. A positive value configures the
generated reconciliation model with `match_amount = "lower"` and this value
as its upper bound.

Omit the key, or use `0`, to create no amount condition:

```python
"maximum_amount": 200,
```

### `analytic_distribution`

Optional mapping describing analytic accounts by plan and the percentage to
assign to them. Use stable external IDs for analytic accounts in code. The
IPLN chart loader resolves them to database IDs before creating the rule.

An analytic account already identifies its analytic plan, so plan external
IDs are not repeated in the mapping. To assign 100% to one analytic account:

```python
"analytic_distribution": {
    "ipln_account.analytic_account_missoes": 100,
},
```

To split one plan between accounts, use separate entries whose percentages
add up to 100:

```python
"analytic_distribution": {
    "my_module.analytic_account_project_a": 60,
    "my_module.analytic_account_project_b": 40,
},
```

To assign the same 100% posting to accounts belonging to different plans,
join their external IDs with a comma:

```python
"analytic_distribution": {
    "my_module.analytic_account_project_a,my_module.analytic_account_region_south": 100,
},
```

Do not put spaces around the comma. The resulting distribution is copied to
the counterpart line of the generated reconciliation model.

### `analytic_tag_ids`

Optional analytic tags assigned to the generated counterpart line. In a chart
declaration, use a comma-separated string of stable external IDs:

```python
"analytic_tag_ids": (
    "ipln_account.analytic_tag_oferta_destinada_missoes,"
    "my_module.analytic_tag_second"
),
```

For a single tag, use only its external ID. Do not include spaces around the
comma. The Odoo chart loader converts these references into the required
many-to-many command.

When creating a rule directly through the ORM instead, use the usual Odoo
relational commands, for example `Command.set([tag.id])`.

### `reconcile_model_id`

Generated, read-only relation. Do not include it in code declarations. It
points to the standard `account.reconcile.model` maintained by the rule.

The inverse `source_cents_rule_id` on the reconciliation model identifies its
source, and a database constraint prevents more than one generated model from
being linked to the same rule.

## Complete example with analytic dimensions

```python
PIX_RECONCILE_RULES = [
    {
        "name": "PIX designated for missions",
        "active": True,
        "sequence": 20,
        "cents": 7,
        "counterpart_account_code": "4.02.03",
        "maximum_amount": 200,
        "analytic_distribution": {
            "ipln_account.analytic_account_missoes": 100,
        },
        "analytic_tag_ids": (
            "ipln_account.analytic_tag_oferta_destinada_missoes"
        ),
    },
]
```

The referenced analytic accounts and tags must be loaded before the chart
template creates the cents rules. In `ipln_account`, they are declared in
`data/analytic.xml`, which is loaded from the module manifest.

## Chart-template integration

The data array is exposed to Odoo by this method:

```python
@template("ipln", "ipln.reconcile.rule.cents")
def _get_ipln_reconcile_rules_by_cents(self):
    ...
```

For each dictionary, the method:

1. derives a stable chart external identifier from `name`;
2. injects the target company;
3. preserves `0` as a cents value instead of treating it as empty;
4. resolves analytic-account external IDs; and
5. returns the values to Odoo's chart loader.

The chart loader then creates or updates `ipln.reconcile.rule.cents`. The
model lifecycle synchronizes the standard reconciliation model, so no change
to the reconciliation runtime lookup is necessary.
