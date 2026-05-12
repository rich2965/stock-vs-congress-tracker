select
  sector,
  n_trades,
  est_buy_volume_30d_by_report / 1000.0 as est_buy_volume_30d_k
from main_gold.gold_sector_congress_buys_30d
order by est_buy_volume_30d_k desc
