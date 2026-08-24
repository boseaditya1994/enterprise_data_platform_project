select
    count(*) as live_agent_attempts,
    count(case when cf.is_rpc_flag then 1 end) as right_party_contacts,
    right_party_contacts::double / nullif(live_agent_attempts, 0) as call_connect_rate
from "dbt_warehouse"."marts"."fct_contact" cf
join "dbt_warehouse"."marts"."dim_channel" ch on ch.channel_sk = cf.channel_sk
where ch.channel_category = 'Live Agent'