-- Check that the user still holds every seat they want to buy.
-- KEYS[1]=hold:z:<event>  KEYS[2]=hold:h:<event>
-- ARGV[1]=now_ms  ARGV[2]=user_id  ARGV[3]=grace_until_ms  ARGV[4..]=seat ids
-- Returns the seats NOT validly held by the user. When none are missing, holds that would
-- expire before grace_until_ms are extended to it, so they can't lapse mid-purchase.
local missing = {}
for i = 4, #ARGV do
  local seat = ARGV[i]
  local score = redis.call('ZSCORE', KEYS[1], seat)
  if (not score) or tonumber(score) <= tonumber(ARGV[1])
      or redis.call('HGET', KEYS[2], seat) ~= ARGV[2] then
    missing[#missing + 1] = seat
  end
end
if #missing == 0 then
  for i = 4, #ARGV do
    if tonumber(redis.call('ZSCORE', KEYS[1], ARGV[i])) < tonumber(ARGV[3]) then
      redis.call('ZADD', KEYS[1], ARGV[3], ARGV[i])
    end
  end
end
return missing
