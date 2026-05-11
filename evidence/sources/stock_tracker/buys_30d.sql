select
  sector,
  est_buy_volume_30d_by_report / 1000.0 as est_buy_volume_30d_k
from gold.gold_sector_congress_buys_30d
where sector is not null
order by est_buy_volume_30d_k desc
