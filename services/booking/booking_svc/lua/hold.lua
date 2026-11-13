-- Hold seats for one user: all requested seats or none.
-- KEYS[1]=hold:z:<event>  KEYS[2]=hold:h:<event>  KEYS[3]=sold:<event>
-- ARGV[1]=now_ms  ARGV[2]=expires_at_ms  ARGV[3]=user_id  ARGV[4..]=seat ids
-- Returns the conflicting seats; an empty list means every seat is now held by the user.

-- Drop expired holds first so their seats count as free. One HDEL per seat instead of
-- unpack(): unpack() of thousands of expired seats would overflow the Lua stack.
local expired = redis.call('ZRANGEBYSCORE', KEYS[1], '-inf', ARGV[1])
if #expired > 0 then
  redis.call('ZREMRANGEBYSCORE', KEYS[1], '-inf', ARGV[1])
  for _, seat in ipairs(expired) do
    redis.call('HDEL', KEYS[2], seat)
  end
end

local conflicts = {}
for i = 4, #ARGV do
  local seat = ARGV[i]
  if redis.call('SISMEMBER', KEYS[3], seat) == 1 then
    conflicts[#conflicts + 1] = seat
  elseif redis.call('ZSCORE', KEYS[1], seat) then
    if redis.call('HGET', KEYS[2], seat) ~= ARGV[3] then
      conflicts[#conflicts + 1] = seat
    end
  end
end
if #conflicts > 0 then
  return conflicts
end

for i = 4, #ARGV do
  redis.call('ZADD', KEYS[1], ARGV[2], ARGV[i]) -- re-holding your own seat refreshes expiry
  redis.call('HSET', KEYS[2], ARGV[i], ARGV[3])
end
return conflicts
