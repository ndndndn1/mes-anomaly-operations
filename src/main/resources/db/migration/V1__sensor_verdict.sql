create table if not exists sensor_verdict (
  id bigserial primary key,
  line_id varchar(80) not null,
  equipment_id varchar(80) not null,
  sensor varchar(80) not null,
  observed_at timestamptz not null,
  value double precision not null,
  severity varchar(20) not null,
  rule_name varchar(40) not null
);
create index if not exists sensor_verdict_lookup on sensor_verdict(line_id, equipment_id, observed_at desc);
