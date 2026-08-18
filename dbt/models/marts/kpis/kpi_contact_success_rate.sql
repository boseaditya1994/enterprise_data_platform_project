select
    count(*) as live_agent_contacts,
    count(case when exists (
        select 1 from {{ ref('fct_promise_to_pay') }} p where p.contact_id = cf.contact_id
    ) then 1 end) as contacts_resulting_in_ptp,
    contacts_resulting_in_ptp::double / nullif(live_agent_contacts, 0) as contact_success_rate
from {{ ref('fct_contact') }} cf
join {{ ref('dim_channel') }} ch on ch.channel_sk = cf.channel_sk
where ch.channel_category = 'Live Agent'