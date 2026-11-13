-- Release a user's holds. Seats held by someone else are left untouched.
-- KEYS[1]=hold:z:<event>  KEYS[2]=hold:h:<event>
-- ARGV[1]=user_id  ARGV[2..]=seat ids
-- Returns how many seats were released.
local released = 0
for i = 2, #ARGV do
  if redis.call('HGET', KEYS[2], ARGV[i]) == ARGV[1] then
    redis.call('ZREM', KEYS[1], ARGV[i])
    redis.call('HDEL', KEYS[2], ARGV[i])
    released = released + 1
  end
end
return released
