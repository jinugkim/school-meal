/** School meal and weekend Psalm notifications for Google Apps Script. */
const CONFIG = {
  timezone: 'Asia/Seoul',
  neisUrl: 'https://open.neis.go.kr/hub/mealServiceDietInfo',
  kakaoTokenUrl: 'https://kauth.kakao.com/oauth/token',
  kakaoMemoUrl: 'https://kapi.kakao.com/v2/api/talk/memo/default/send',
  holidayCalendarId: 'ko.south_korea#holiday@group.v.calendar.google.com',
  psalmStart: '2026-10-17'
};

const RECIPIENTS = [
  { label: '본인', property: 'KAKAO_REFRESH_TOKEN_ME' },
  { label: '배우자', property: 'KAKAO_REFRESH_TOKEN_WIFE' },
  { label: '딸', property: 'KAKAO_REFRESH_TOKEN_DAUGHTER' }
];

/** Run once to install weekday meal and weekend Psalm triggers. */
function installTriggers() {
  const handlers = ['runScheduledMeal', 'runScheduledPsalm'];
  ScriptApp.getProjectTriggers().forEach(function (trigger) {
    if (handlers.indexOf(trigger.getHandlerFunction()) !== -1) {
      ScriptApp.deleteTrigger(trigger);
    }
  });

  [ScriptApp.WeekDay.MONDAY, ScriptApp.WeekDay.TUESDAY,
    ScriptApp.WeekDay.WEDNESDAY, ScriptApp.WeekDay.THURSDAY,
    ScriptApp.WeekDay.FRIDAY].forEach(function (day) {
    ScriptApp.newTrigger('runScheduledMeal').timeBased()
      .everyWeeks(1).onWeekDay(day).atHour(6).nearMinute(25)
      .inTimezone(CONFIG.timezone).create();
  });
  [ScriptApp.WeekDay.SATURDAY, ScriptApp.WeekDay.SUNDAY].forEach(function (day) {
    ScriptApp.newTrigger('runScheduledPsalm').timeBased()
      .everyWeeks(1).onWeekDay(day).atHour(9).nearMinute(0)
      .inTimezone(CONFIG.timezone).create();
  });
  Logger.log('예약 설치 완료: 평일 급식 약 06:25, 주말 시편 약 09:00 KST');
}

/** Scheduled weekday entry point. */
function runScheduledMeal() {
  return withScriptLock_(function () { return sendMealForDate_(new Date(), true); });
}

/** Manually run from the editor to check today's meal and Kakao configuration. */
function runMealNow() {
  return withScriptLock_(function () { return sendMealForDate_(new Date(), false); });
}

/** Query NEIS and log a preview without refreshing tokens or sending Kakao messages. */
function previewMealNow() {
  const target = dateParts_(new Date());
  const meals = getMeals_(target.key);
  Logger.log('%s NEIS 메뉴 미리보기 (%s)', target.label, meals.length);
  meals.forEach(function (meal) {
    Logger.log('%s\n%s%s', meal.name, meal.dishes.join('\n'), meal.calories ? '\n열량: ' + meal.calories : '');
  });
}

/** Scheduled weekend entry point. */
function runScheduledPsalm() {
  return withScriptLock_(function () { return sendWeekendPsalm_(); });
}

function sendMealForDate_(now, scheduled) {
  const target = dateParts_(now);
  if (scheduled && isWeekend_(now)) {
    Logger.log('주말이므로 급식 알림을 건너뜁니다.');
    return;
  }
  if (isWeekend_(now) || isKoreanHoliday_(now)) {
    Logger.log('%s은(는) 주말 또는 한국 공휴일이므로 급식 발송을 건너뜁니다.', target.label);
    return;
  }

  const properties = PropertiesService.getScriptProperties();
  const apiKey = requiredProperty_(properties, 'NEIS_API_KEY');
  const officeCode = requiredProperty_(properties, 'OFFICE_CODE');
  const schoolCode = requiredProperty_(properties, 'SCHOOL_CODE');
  let meals = getMeals_(target.key, apiKey, officeCode, schoolCode);
  const weekday = Number(Utilities.formatDate(now, CONFIG.timezone, 'u'));
  meals = meals.filter(function (meal) {
    return meal.name !== '석식' || ((weekday === 2 || weekday === 4) && !isKoreanHoliday_(now));
  });
  if (!meals.length) {
    Logger.log('%s 등록된 발송 대상 급식이 없습니다. 전송하지 않습니다.', target.label);
    return;
  }

  const messages = meals.map(function (meal) { return formatMealMessage_(target.label, meal); });
  Logger.log('대상 날짜: %s / 메뉴: %s', target.key, meals.map(function (m) { return m.name; }).join(', '));
  if (properties.getProperty('DRY_RUN') === 'true') {
    messages.forEach(function (message) { Logger.log('DRY_RUN 메시지 미리보기:\n%s', message); });
    return;
  }
  sendToRecipients_(messages, meals.map(function (meal) { return meal.name; }));
}

function getMeals_(mealDate, apiKey, officeCode, schoolCode) {
  const properties = PropertiesService.getScriptProperties();
  apiKey = apiKey || requiredProperty_(properties, 'NEIS_API_KEY');
  officeCode = officeCode || requiredProperty_(properties, 'OFFICE_CODE');
  schoolCode = schoolCode || requiredProperty_(properties, 'SCHOOL_CODE');
  const query = {
    KEY: apiKey, Type: 'json', pIndex: 1, pSize: 100,
    ATPT_OFCDC_SC_CODE: officeCode, SD_SCHUL_CODE: schoolCode, MLSV_YMD: mealDate
  };
  const url = CONFIG.neisUrl + '?' + Object.keys(query).map(function (key) {
    return encodeURIComponent(key) + '=' + encodeURIComponent(query[key]);
  }).join('&');
  const response = UrlFetchApp.fetch(url, { muteHttpExceptions: true, followRedirects: true });
  const status = response.getResponseCode();
  if (status < 200 || status >= 300) throw new Error('NEIS 조회 실패 (HTTP ' + status + ')');
  const payload = JSON.parse(response.getContentText());
  if (!payload.mealServiceDietInfo) {
    const result = payload.RESULT || {};
    if (result.CODE === 'INFO-200' || result.CODE === 'INFO-201') return [];
    throw new Error('NEIS 응답 오류: ' + (result.MESSAGE || '급식 정보가 없습니다.'));
  }
  const rows = payload.mealServiceDietInfo[payload.mealServiceDietInfo.length - 1].row || [];
  const meals = {};
  rows.forEach(function (row) {
    const name = String(row.MMEAL_SC_NM || '').trim() || '급식';
    if (!meals[name]) meals[name] = { name: name, dishes: [], calories: [] };
    cleanDishName_(row.DDISH_NM || '').split('\n').forEach(function (dish) {
      if (dish.trim()) meals[name].dishes.push(dish.trim());
    });
    if (row.CAL_INFO) meals[name].calories.push(String(row.CAL_INFO).trim());
  });
  return Object.keys(meals).map(function (name) {
    const meal = meals[name];
    meal.calories = meal.calories.filter(function (value, index, all) { return all.indexOf(value) === index; }).join(' / ');
    return meal;
  }).filter(function (meal) { return meal.dishes.length > 0; });
}

function cleanDishName_(value) {
  return String(value).replace(/<br\s*\/?\s*>/gi, '\n')
    .replace(/\([^)]*\)/g, function (part) { return part.replace(/\d+(?:\.\d+)*\.?/g, ''); })
    .replace(/\(\s*\)/g, '').replace(/\d+(?:\.\d+)*\.(?=\s|$)/g, '')
    .replace(/[ \t]+/g, ' ').trim();
}

function formatMealMessage_(dateLabel, meal) {
  const message = '🍚 ' + dateLabel + ' 오늘 ' + meal.name + '\n\n' +
    meal.dishes.map(function (dish) { return '• ' + dish; }).join('\n') +
    (meal.calories ? '\n열량: ' + meal.calories : '');
  return message.length <= 200 ? message : message.slice(0, 199) + '…';
}

function sendToRecipients_(messages, mealNames, linkUrl, buttonTitle) {
  const properties = PropertiesService.getScriptProperties();
  const restKey = requiredProperty_(properties, 'KAKAO_REST_API_KEY');
  const clientSecret = properties.getProperty('KAKAO_CLIENT_SECRET') || '';
  const recipients = loadRecipients_(properties);
  const errors = [];
  let ownerAccessToken = null;
  recipients.forEach(function (recipient) {
    try {
      const tokenResult = refreshAccessToken_(properties, recipient, restKey, clientSecret);
      if (recipient.label === '본인') ownerAccessToken = tokenResult.accessToken;
      messages.forEach(function (message, index) {
        try {
          sendKakaoMessage_(tokenResult.accessToken, message, linkUrl, buttonTitle);
          Logger.log('%s 계정 메시지 발송 성공: %s', recipient.label, mealNames[index]);
        } catch (error) {
          Logger.log('%s 계정 %s 메시지 발송 실패: %s', recipient.label, mealNames[index], error.message);
          errors.push(recipient.label + ' 계정 ' + mealNames[index] + ' 전송 실패. Apps Script 실행 로그를 확인해 주세요.');
        }
      });
    } catch (error) {
      Logger.log('%s 계정 발송 실패: %s', recipient.label, error.message);
      errors.push(recipient.label + ' 계정 급식 전송 실패. Apps Script 실행 로그를 확인해 주세요.');
    }
  });
  if (errors.length && ownerAccessToken) {
    errors.forEach(function (message) {
      try { sendKakaoMessage_(ownerAccessToken, '⚠️ 급식 알림 시스템 안내\n' + message); }
      catch (error) { Logger.log('운영 안내 전송 실패: %s', error.message); }
    });
  }
  if (errors.length) throw new Error(errors.join(' / '));
}

function loadRecipients_(properties) {
  const recipients = RECIPIENTS.map(function (item) {
    return { label: item.label, property: item.property, token: properties.getProperty(item.property) || '' };
  }).filter(function (item) { return item.token.trim(); });
  if (recipients.length) return recipients;
  const raw = properties.getProperty('KAKAO_REFRESH_TOKENS') || '';
  if (!raw.trim()) throw new Error('KAKAO_REFRESH_TOKEN_ME/WIFE/DAUGHTER 중 하나 이상 설정하세요.');
  let values;
  try { values = JSON.parse(raw); } catch (error) { values = raw.split(','); }
  if (typeof values === 'string') values = [values];
  if (!Array.isArray(values)) throw new Error('KAKAO_REFRESH_TOKENS는 JSON 문자열 배열이어야 합니다.');
  return values.map(function (token, index) {
    const property = 'KAKAO_REFRESH_TOKENS_' + index;
    return { label: '계정 ' + (index + 1), property: property,
      token: properties.getProperty(property) || String(token).trim() };
  }).filter(function (item) { return item.token; });
}

function refreshAccessToken_(properties, recipient, restKey, clientSecret) {
  const form = { grant_type: 'refresh_token', client_id: restKey, refresh_token: recipient.token };
  if (clientSecret) form.client_secret = clientSecret;
  const response = UrlFetchApp.fetch(CONFIG.kakaoTokenUrl, {
    method: 'post', payload: form, muteHttpExceptions: true
  });
  const body = JSON.parse(response.getContentText() || '{}');
  if (response.getResponseCode() < 200 || response.getResponseCode() >= 300) {
    throw new Error('카카오 토큰 갱신 실패 (' + response.getResponseCode() + '): ' +
      [body.error, body.error_description].filter(Boolean).join(' '));
  }
  if (!body.access_token) throw new Error('카카오 토큰 응답에 access_token이 없습니다.');
  if (body.refresh_token) {
    properties.setProperty(recipient.property, body.refresh_token);
    recipient.token = body.refresh_token;
    Logger.log('%s 계정 refresh token이 교체되어 Script Properties에 저장했습니다.', recipient.label);
  }
  return { accessToken: body.access_token };
}

function sendKakaoMessage_(accessToken, message, linkUrl, buttonTitle) {
  const template = {
    object_type: 'text', text: message.slice(0, 200),
    link: { web_url: linkUrl || 'https://open.neis.go.kr', mobile_web_url: linkUrl || 'https://open.neis.go.kr' },
    button_title: buttonTitle || '나이스 급식 정보'
  };
  const response = UrlFetchApp.fetch(CONFIG.kakaoMemoUrl, {
    method: 'post', headers: { Authorization: 'Bearer ' + accessToken },
    payload: { template_object: JSON.stringify(template) }, muteHttpExceptions: true
  });
  const body = JSON.parse(response.getContentText() || '{}');
  if (response.getResponseCode() < 200 || response.getResponseCode() >= 300 || body.result_code !== 0) {
    throw new Error('카카오 메시지 전송 실패 (' + response.getResponseCode() + '): ' + (body.msg || body.error_description || body.code || '응답 오류'));
  }
}

function isKoreanHoliday_(date) {
  const properties = PropertiesService.getScriptProperties();
  const calendarId = properties.getProperty('KOREAN_HOLIDAY_CALENDAR_ID') || CONFIG.holidayCalendarId;
  const calendar = CalendarApp.getCalendarById(calendarId);
  if (!calendar) throw new Error('한국 공휴일 캘린더를 찾을 수 없습니다. KOREAN_HOLIDAY_CALENDAR_ID 설정을 확인하세요.');
  return calendar.getEventsForDay(date).length > 0;
}

function sendWeekendPsalm_() {
  const now = new Date();
  const weekday = Number(Utilities.formatDate(now, CONFIG.timezone, 'u'));
  if (weekday !== 6 && weekday !== 7) {
    Logger.log('주말 시편 예약일이 아니므로 건너뜁니다.');
    return;
  }
  const start = new Date(CONFIG.psalmStart + 'T00:00:00+09:00');
  const todayKey = Utilities.formatDate(now, CONFIG.timezone, 'yyyy-MM-dd');
  const days = Math.floor((new Date(todayKey + 'T00:00:00+09:00').getTime() - start.getTime()) / 86400000);
  if (days < 0) { Logger.log('시편 발송 시작일 전입니다.'); return; }
  const weeks = psalmWeeks_();
  const weekIndex = Math.floor(days / 7) % weeks.length;
  const message = weeks[weekIndex][weekday === 6 ? 0 : 1];
  const properties = PropertiesService.getScriptProperties();
  if (properties.getProperty('DRY_RUN') === 'true') { Logger.log('DRY_RUN 시편 미리보기:\n%s', message); return; }
  sendToRecipients_([message], ['주말 시편'], 'https://ebible.org/engwebu/', 'Psalms');
  Logger.log('주말 시편 %d주차 발송 완료 (%s)', weekIndex + 1, todayKey);
}

function psalmWeeks_() {
  return [
    ["The LORD is my shepherd; I shall lack nothing.\n— Psalm 23:1", "Surely goodness and loving kindness shall follow me all the days of my life.\n— Psalm 23:6"],
    ["Show me your ways, LORD. Teach me your paths.\n— Psalm 25:4", "The LORD is my light and my salvation. Whom shall I fear?\n— Psalm 27:1"],
    ["One thing I have asked of the LORD, that I will seek after: that I may dwell in the LORD’s house.\n— Psalm 27:4", "The LORD will give strength to his people. The LORD will bless his people with peace.\n— Psalm 29:11"],
    ["Weeping may stay for the night, but joy comes in the morning.\n— Psalm 30:5", "You have turned my mourning into dancing.\n— Psalm 30:11"],
    ["I will be glad and rejoice in your loving kindness, for you have seen my affliction.\n— Psalm 31:7", "Be strong, and let your heart take courage, all you who hope in the LORD.\n— Psalm 31:24"],
    ["You are my hiding place. You will preserve me from trouble.\n— Psalm 32:7", "I will instruct you and teach you in the way which you shall go.\n— Psalm 32:8"],
    ["He loves righteousness and justice. The earth is full of the loving kindness of the LORD.\n— Psalm 33:5", "Our soul has waited for the LORD. He is our help and our shield.\n— Psalm 33:20"],
    ["I sought the LORD, and he answered me, and delivered me from all my fears.\n— Psalm 34:4", "The LORD is near to those who have a broken heart, and saves those who have a crushed spirit.\n— Psalm 34:18"],
    ["Your loving kindness, LORD, is in the heavens. Your faithfulness reaches to the skies.\n— Psalm 36:5", "How precious is your loving kindness, God! The children of men take refuge under the shadow of your wings.\n— Psalm 36:7"],
    ["Trust in the LORD, and do good. Dwell in the land, and enjoy safe pasture.\n— Psalm 37:3", "Delight yourself in the LORD, and he will give you the desires of your heart.\n— Psalm 37:4"],
    ["Commit your way to the LORD. Trust also in him, and he will do this.\n— Psalm 37:5", "The steps of a good man are established by the LORD. He delights in his way.\n— Psalm 37:23"],
    ["I waited patiently for the LORD. He turned to me, and heard my cry.\n— Psalm 40:1", "He has put a new song in my mouth, even praise to our God.\n— Psalm 40:3"],
    ["As the deer pants for the water brooks, so my soul pants after you, God.\n— Psalm 42:1", "Hope in God! For I shall still praise him for the saving help of his presence.\n— Psalm 42:5"],
    ["God is our refuge and strength, a very present help in trouble.\n— Psalm 46:1", "Be still, and know that I am God.\n— Psalm 46:10"],
    ["Create in me a clean heart, O God. Renew a right spirit within me.\n— Psalm 51:10", "Restore to me the joy of your salvation. Uphold me with a willing spirit.\n— Psalm 51:12"],
    ["Cast your burden on the LORD and he will sustain you.\n— Psalm 55:22", "As for me, I will call on God. The LORD will save me.\n— Psalm 55:16"],
    ["When I am afraid, I will put my trust in you.\n— Psalm 56:3", "In God, I praise his word. In God, I put my trust. I will not be afraid.\n— Psalm 56:4"],
    ["My heart is steadfast, God. My heart is steadfast. I will sing, yes, I will sing praises.\n— Psalm 57:7", "Because your loving kindness is better than life, my lips shall praise you.\n— Psalm 63:3"],
    ["From the end of the earth, I will call to you, when my heart is overwhelmed. Lead me to the rock that is higher than I.\n— Psalm 61:2", "You have been my refuge, a strong tower from the enemy.\n— Psalm 61:3"],
    ["My soul rests in God alone. My salvation is from him.\n— Psalm 62:1", "My soul, wait in silence for God alone, for my expectation is from him.\n— Psalm 62:5"],
    ["For you have been my help. I will rejoice in the shadow of your wings.\n— Psalm 63:7", "Make a joyful shout to God, all the earth!\n— Psalm 66:1"],
    ["Blessed be God, who has not turned away my prayer, nor his loving kindness from me!\n— Psalm 66:20", "For you are my hope, Lord GOD; my confidence from my youth.\n— Psalm 71:5"],
    ["My lips shall shout for joy! My soul, which you have redeemed, sings praises to you!\n— Psalm 71:23", "My flesh and my heart fails, but God is the strength of my heart and my portion forever.\n— Psalm 73:26"],
    ["For the LORD God is a sun and a shield. The LORD will give grace and glory.\n— Psalm 84:11", "LORD of Armies, blessed is the man who trusts in you.\n— Psalm 84:12"],
    ["For you, Lord, are good, and ready to forgive, abundant in loving kindness to all those who call on you.\n— Psalm 86:5", "Teach me your way, LORD. I will walk in your truth.\n— Psalm 86:11"],
    ["So teach us to count our days, that we may gain a heart of wisdom.\n— Psalm 90:12", "Let the favor of the Lord our God be on us. Establish the work of our hands.\n— Psalm 90:17"],
    ["He who dwells in the secret place of the Most High will rest in the shadow of the Almighty.\n— Psalm 91:1", "I will say of the LORD, “He is my refuge and my fortress; my God, in whom I trust.”\n— Psalm 91:2"],
    ["It is a good thing to give thanks to the LORD, to sing praises to your name, Most High.\n— Psalm 92:1", "For you, LORD, have made me glad through your work. I will triumph in the works of your hands.\n— Psalm 92:4"],
    ["In the multitude of my thoughts within me, your comforts delight my soul.\n— Psalm 94:19", "The LORD has been my high tower, my God, the rock of my refuge.\n— Psalm 94:22"],
    ["Oh come, let’s sing to the LORD. Let’s shout aloud to the rock of our salvation!\n— Psalm 95:1", "Let’s come before his presence with thanksgiving. Let’s extol him with songs!\n— Psalm 95:2"],
    ["Serve the LORD with gladness. Come before his presence with singing.\n— Psalm 100:2", "For the LORD is good. His loving kindness endures forever, his faithfulness to all generations.\n— Psalm 100:5"],
    ["Praise the LORD, my soul, and don’t forget all his benefits.\n— Psalm 103:2", "The LORD is merciful and gracious, slow to anger, and abundant in loving kindness.\n— Psalm 103:8"],
    ["Give thanks to the LORD, for he is good, for his loving kindness endures forever.\n— Psalm 107:1", "For he satisfies the longing soul. He fills the hungry soul with good.\n— Psalm 107:9"],
    ["Light dawns in the darkness for the upright, gracious, merciful, and righteous.\n— Psalm 112:4", "He will not be afraid of evil news. His heart is steadfast, trusting in the LORD.\n— Psalm 112:7"],
    ["I love the LORD, because he listens to my voice, and my cries for mercy.\n— Psalm 116:1", "Return to your rest, my soul, for the LORD has dealt bountifully with you.\n— Psalm 116:7"],
    ["The LORD is on my side. I will not be afraid. What can man do to me?\n— Psalm 118:6", "This is the day that the LORD has made. We will rejoice and be glad in it!\n— Psalm 118:24"],
    ["Your word is a lamp to my feet, and a light for my path.\n— Psalm 119:105", "You are my hiding place and my shield. I hope in your word.\n— Psalm 119:114"],
    ["My help comes from the LORD, who made heaven and earth.\n— Psalm 121:2", "The LORD will keep your going out and your coming in, from this time forward, and forever more.\n— Psalm 121:8"],
    ["The LORD has done great things for us, and we are glad.\n— Psalm 126:3", "Those who sow in tears will reap in joy.\n— Psalm 126:5"],
    ["Unless the LORD builds the house, they labor in vain who build it.\n— Psalm 127:1", "Behold, children are a heritage of the LORD.\n— Psalm 127:3"],
    ["I wait for the LORD. My soul waits. I hope in his word.\n— Psalm 130:5", "My soul longs for the Lord more than watchmen long for the morning.\n— Psalm 130:6"],
    ["Give thanks to the LORD, for he is good, for his loving kindness endures forever.\n— Psalm 136:1", "Give thanks to the God of heaven, for his loving kindness endures forever.\n— Psalm 136:26"],
    ["I will give thanks to you, for I am fearfully and wonderfully made.\n— Psalm 139:14", "Search me, God, and know my heart. Try me, and know my thoughts.\n— Psalm 139:23"],
    ["Cause me to hear your loving kindness in the morning, for I trust in you.\n— Psalm 143:8", "Teach me to do your will, for you are my God. Your Spirit is good.\n— Psalm 143:10"],
    ["The LORD is gracious, merciful, slow to anger, and of great loving kindness.\n— Psalm 145:8", "The LORD is near to all those who call on him, to all who call on him in truth.\n— Psalm 145:18"],
    ["Happy is he who has the God of Jacob for his help, whose hope is in the LORD, his God.\n— Psalm 146:5", "The LORD opens the eyes of the blind. The LORD raises up those who are bowed down.\n— Psalm 146:8"],
    ["He heals the broken in heart, and binds up their wounds.\n— Psalm 147:3", "Great is our Lord, and mighty in power. His understanding is infinite.\n— Psalm 147:5"],
    ["He counts the number of the stars. He calls them all by their names.\n— Psalm 147:4", "Praise the LORD! For it is good to sing praises to our God.\n— Psalm 147:1"],
    ["Praise the LORD! Praise God in his sanctuary!\n— Psalm 150:1", "Let everything that has breath praise the LORD! Praise the LORD!\n— Psalm 150:6"],
    ["The LORD is my strength and song. He has become my salvation.\n— Psalm 118:14", "Oh give thanks to the LORD, for he is good, for his loving kindness endures forever.\n— Psalm 118:29"],
    ["The LORD is my rock, my fortress, and my deliverer.\n— Psalm 18:2", "In my distress I called on the LORD, and cried to my God.\n— Psalm 18:6"],
    ["The LORD is gracious and righteous. Yes, our God is merciful.\n— Psalm 116:5", "I will walk before the LORD in the land of the living.\n— Psalm 116:9"],
    ["The earth is the LORD’s, with its fullness; the world, and those who dwell in it.\n— Psalm 24:1", "Who may ascend to the LORD’s hill? Who may stand in his holy place?\n— Psalm 24:3"],
    ["The LORD is good to all. His tender mercies are over all his works.\n— Psalm 145:9", "The eyes of all wait for you. You give them their food in due season.\n— Psalm 145:15"],
    ["The LORD will reign forever; your God, O Zion, to all generations. Praise the LORD!\n— Psalm 146:10", "Sing to the LORD with thanksgiving.\n— Psalm 147:7"]
  ];
}

function requiredProperty_(properties, key) {
  const value = (properties.getProperty(key) || '').trim();
  if (!value) throw new Error('필수 Script Property가 설정되지 않았습니다: ' + key);
  return value;
}

function dateParts_(date) {
  const key = Utilities.formatDate(date, CONFIG.timezone, 'yyyyMMdd');
  return { key: key, label: Utilities.formatDate(date, CONFIG.timezone, 'yyyy년 MM월 dd일') };
}

function isWeekend_(date) {
  const day = Number(Utilities.formatDate(date, CONFIG.timezone, 'u'));
  return day === 6 || day === 7;
}

function withScriptLock_(callback) {
  const lock = LockService.getScriptLock();
  if (!lock.tryLock(1000)) throw new Error('다른 급식 알림 실행이 진행 중입니다.');
  try { return callback(); } finally { lock.releaseLock(); }
}
