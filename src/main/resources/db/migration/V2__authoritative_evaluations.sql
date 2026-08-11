create table evaluation_event (
  event_id varchar(80) primary key,
  line_id varchar(80) not null,
  equipment_id varchar(80) not null,
  request_hash char(64) not null,
  request_path varchar(80) not null,
  response_body text,
  created_at timestamptz not null default clock_timestamp(),
  completed_at timestamptz,
  constraint evaluation_event_completion check (
    (completed_at is null and response_body is null)
    or (completed_at is not null and response_body is not null)
  )
);

create index evaluation_event_equipment_created
  on evaluation_event(line_id, equipment_id, created_at desc);

create table sensor_sample (
  id bigserial primary key,
  event_id varchar(80) not null references evaluation_event(event_id),
  line_id varchar(80) not null,
  equipment_id varchar(80) not null,
  sensor varchar(80) not null,
  observed_at timestamptz not null,
  value double precision not null,
  constraint sensor_sample_finite check (
    value between '-1.7976931348623157e308'::double precision
      and '1.7976931348623157e308'::double precision
  )
);

create index sensor_sample_history
  on sensor_sample(line_id, equipment_id, sensor, observed_at desc, id desc);

alter table sensor_verdict add column event_id varchar(80) references evaluation_event(event_id);
alter table sensor_verdict add column score double precision;
alter table sensor_verdict add constraint sensor_verdict_score_finite
  check (score is null or score between '-1.7976931348623157e308'::double precision
      and '1.7976931348623157e308'::double precision);
create index sensor_verdict_event on sensor_verdict(event_id);
