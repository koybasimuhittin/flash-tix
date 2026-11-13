-- Mark seats as sold after the purchase transaction committed.
-- KEYS[1]=hold:z:<event>  KEYS[2]=hold:h:<event>  KEYS[3]=sold:<event>
-- ARGV[1..]=seat ids
-- The sold set is only a cache of the database; Postgres' UNIQUE(event_id, seat_id) decides.
for i = 1, #ARGV do
  redis.call('SADD', KEYS[3], ARGV[i])
  redis.call('ZREM', KEYS[1], ARGV[i])
  redis.call('HDEL', KEYS[2], ARGV[i])
end
return #ARGV
