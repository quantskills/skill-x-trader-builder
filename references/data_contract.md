# Data Contract

Preferred input columns:

- `signal_id`
- `post_id`
- `created_at`
- `author`
- `url`
- `ticker`
- `text`
- `quoted_author`
- `quoted_text`
- `theme`
- `evidence_types`
- `supply_chain_role`
- `risk_markers`
- `conviction_score`
- `engagement_score`

Minimum usable columns:

- `text`
- either `ticker` or cashtags in `text`

The script preserves existing columns and appends review fields.

Review fields:

- `ticker_in_main_text`
- `ticker_in_quoted_text`
- `view_owner`
- `timing_type`
- `signal_type`
- `review_decision`
- `signal_weight`
- `review_reason`
- `needs_followup`

Recommended split:

- `keep`: high-quality active thesis
- `keep_deweighted`: valid main-text signal, but broad or under-specified
- `deweight`: watchlist, candidate pool, or pre-DD idea
- `delete_from_this_signal`: ticker appears only in quote context
- `remove_from_forward_signal_keep_as_track_record_context`: retrospective return or track-record post
- `keep_as_explainer_deweight`: event explanation, not explicit long/short thesis
- `delete`: unusable link-only or empty row
