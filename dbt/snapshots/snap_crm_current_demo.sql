{% snapshot snap_crm_current_demo %}

{{
    config(
        target_schema='snapshots',
        unique_key='customer_id',
        strategy='check',
        check_cols=['mailing_city', 'mailing_state', 'mailing_zip', 'customer_segment', 'employment_status'],
    )
}}

select * from {{ ref('stg_crm__customers_current_simulated') }}

{% endsnapshot %}
