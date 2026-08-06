
  
  create view "dbt_warehouse"."marts"."kpi_contact_success_rate__dbt_tmp" as (
    select
    count(*) as live_agent_contacts,
    count(*) filter (
        where exists (select 1 from "dbt_warehouse"."marts"."fct_promise_to_pay" p where p.contact_id = cf.contact_id)
    ) as contacts_resulting_in_ptp,
    contacts_resulting_in_ptp::double / nullif(live_agent_contacts, 0) as contact_success_rate
from "dbt_warehouse"."marts"."fct_contact" cf
join "dbt_warehouse"."marts"."dim_channel" ch on ch.channel_sk = cf.channel_sk
where ch.channel_category = 'Live Agent'
  );
