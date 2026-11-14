"""Catalogue of deliberately injected source-data defects.

Each defect has a matching custom dbt test in ``warehouse/tests/`` that fails if the
modelling layer stops handling it, and a pytest in ``tests/`` that proves the defect is
actually present in the raw data.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Defect:
    code: str
    name: str
    where: str
    description: str
    dbt_test: str


DEFECTS: tuple[Defect, ...] = (
    Defect(
        code="D1",
        name="UTM casing drift",
        where="web_sessions.utm_source / utm_medium / utm_campaign",
        description="UTM values arrive in random case with stray whitespace ('Google', ' LINKEDIN', 'Brand-Search ').",
        dbt_test="assert_utm_values_normalised",
    ),
    Defect(
        code="D2",
        name="Duplicate leads",
        where="crm_leads.email",
        description="~6% of people get a second lead (list import / manual entry) whose email "
        "differs only by case or whitespace.",
        dbt_test="assert_one_stitched_lead_per_person",
    ),
    Defect(
        code="D3",
        name="Timezone mismatch",
        where="form_fills.submitted_at",
        description="Form fills are naive America/New_York wall-clock times while every other "
        "timestamp is UTC; read naively, fills appear 4-5h before their session.",
        dbt_test="assert_form_fill_after_session",
    ),
    Defect(
        code="D4",
        name="Renamed campaign",
        where="ad_spend.campaign_name, web_sessions.utm_campaign",
        description="LinkedIn campaign li_2001 is renamed mid-period; spend rows and UTMs carry the "
        "old name before the rename date and the new name after.",
        dbt_test="assert_renamed_campaign_single_dim_row",
    ),
)

RENAMED_CAMPAIGN_ID = "li_2001"
RENAME_DATE = "2025-11-15"
DUPLICATE_LEAD_RATE = 0.06
