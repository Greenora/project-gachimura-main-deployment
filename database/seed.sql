-- Gachimura Database Seed Data Script
USE gachimura;
SET NAMES utf8mb4;

SET FOREIGN_KEY_CHECKS = 0;
TRUNCATE TABLE settlement_item_members;
TRUNCATE TABLE settlement_items;
TRUNCATE TABLE settlement_payments;
TRUNCATE TABLE settlements;
TRUNCATE TABLE evaluations;
TRUNCATE TABLE community_post_likes;
TRUNCATE TABLE community_comments;
TRUNCATE TABLE community_posts;
TRUNCATE TABLE chat_messages;
TRUNCATE TABLE party_members;
TRUNCATE TABLE parties;
TRUNCATE TABLE users;
SET FOREIGN_KEY_CHECKS = 1;

-- 1. Users (일반 유저 비밀번호: password123, 관리자 계정 비밀번호: admin1234)
-- bcrypt hash for 'password123': $2b$10$5vAGXLlzoXk5CfsCiBi2QuAAP9kMShthkT7qDpV1UZ8i8/sIiPcJG
-- bcrypt hash for 'admin1234':   $2b$10$QmITUMScIV8Zv64CmBuy0.pU/SQC1OmSo/KKODyx07GqeBrWsPJrq
INSERT INTO users (id, email, password, nickname, nickname_jp, provider, treeScore, region, district, latitude, longitude, created_at, updated_at) VALUES
(1, 'hong@test.com', '$2b$10$5vAGXLlzoXk5CfsCiBi2QuAAP9kMShthkT7qDpV1UZ8i8/sIiPcJG', '코끼리', 'ゾウ', 'LOCAL', 80.0, '서울특별시', '마포구', 37.56380000, 126.90840000, NOW(), NOW()),
(2, 'kim@test.com', '$2b$10$5vAGXLlzoXk5CfsCiBi2QuAAP9kMShthkT7qDpV1UZ8i8/sIiPcJG', '김철수', 'チェルス', 'LOCAL', 65.5, '서울특별시', '중구', 37.56410000, 126.99790000, NOW(), NOW()),
(3, 'lee@test.com', '$2b$10$5vAGXLlzoXk5CfsCiBi2QuAAP9kMShthkT7qDpV1UZ8i8/sIiPcJG', '기린', 'キリン', 'LOCAL', 50.0, '도쿄도', '신주쿠구', 35.69380000, 139.70340000, NOW(), NOW()),
(4, 'soil@test.com', '$2b$10$5vAGXLlzoXk5CfsCiBi2QuAAP9kMShthkT7qDpV1UZ8i8/sIiPcJG', '흙투성이', 'ツチツチ', 'LOCAL', 18.0, '오사카부', '나니와구', 34.66870000, 135.49520000, NOW(), NOW()),
(5, 'admin@gmail.com', '$2b$10$QmITUMScIV8Zv64CmBuy0.pU/SQC1OmSo/KKODyx07GqeBrWsPJrq', '관리자', '管理者', 'LOCAL', 99.0, '서울특별시', '강남구', 37.49790000, 127.02760000, NOW(), NOW());

-- 2. Parties (모임 파티)
INSERT INTO parties (id, host_id, title, content, store_name, address, address_ko, address_jp, latitude, longitude, meet_date, capacity, current_count, status, created_at, updated_at) VALUES
(1, 1, '코스트코 소고기 같이 사실 분!', '미국산 프라임 척아이롤 양이 너무 많아서 2~3분 나누실 분 구합니다.', '코스트코 양재점', '서울 서초구 양재대로 159', '서울 서초구 양재대로 159', 'ソウル特別市 瑞草区 良才大路 159', 37.46260000, 127.03750000, '2026-11-12 15:00:00', 4, 2, 'RECRUITING', NOW(), NOW()),
(2, 2, '이마트 1+1 만두 나눠요', 'CJ 비비고 왕교자 1+1 행사하는데 한 봉지씩 나누실 분 구해요.', '이마트 용산점', '서울 용산구 한강대로23길 55', '서울 용산구 한강대로23길 55', 'ソウル特別市 龍山区 漢江大路23吉 55', 37.52980000, 126.96470000, '2026-11-15 18:30:00', 2, 2, 'RECRUITING', NOW(), NOW()),
(3, 3, '신주쿠 돈키호테 의약품/과자 대량 구매', '돈키호테 할인 쿠폰 혜택 같이 받으실 분 모십니다.', '돈키호테 신주쿠점', '東京都新宿区歌舞伎町1-16-5', '東京都新宿区歌舞伎町1-16-5', '東京都新宿区歌舞伎町1-16-5', 35.69380000, 139.70340000, '2026-12-01 14:00:00', 3, 1, 'RECRUITING', NOW(), NOW()),
(4, 4, '도톤보리 라이프 마트 연어 사시미 소분', '대용량 연어 사시미 반반 나누실 분 계신가요?', '라이프 마트 난바점', '大阪府大阪市浪速区湊町1-2-3', '大阪府大阪市浪速区湊町1-2-3', '大阪府大阪市浪速区湊町1-2-3', 34.66870000, 135.49520000, '2026-12-05 19:00:00', 2, 1, 'RECRUITING', NOW(), NOW());

-- 3. Party Members (파티 참여자)
INSERT INTO party_members (id, party_id, user_id, status, is_muted, joined_at, updated_at) VALUES
(1, 1, 1, 'APPROVED', 0, NOW(), NOW()),
(2, 1, 2, 'APPROVED', 0, NOW(), NOW()),
(3, 2, 2, 'APPROVED', 0, NOW(), NOW()),
(4, 2, 3, 'APPROVED', 0, NOW(), NOW()),
(5, 3, 3, 'APPROVED', 0, NOW(), NOW()),
(6, 4, 4, 'APPROVED', 0, NOW(), NOW());

-- 4. Community Posts (커뮤니티 글)
INSERT INTO community_posts (id, author_id, linked_party_id, content, locale, created_at, updated_at) VALUES
(1, 1, 1, '오늘 코스트코 소고기 척아이롤 등급 너무 좋네요! 소분 파티 오실 분 환영합니다. #코스트코 #소고기 #소분', 'ko', DATE_SUB(NOW(), INTERVAL 3 HOUR), DATE_SUB(NOW(), INTERVAL 3 HOUR)),
(2, 2, 2, '이마트 용산점 저녁 7시 넘어가면 릴레이 할인 시작하네요 꿀팁 공유! #이마트 #장보기 #할인', 'ko', DATE_SUB(NOW(), INTERVAL 2 HOUR), DATE_SUB(NOW(), INTERVAL 2 HOUR)),
(3, 3, NULL, '도쿄 신주쿠 근처 알뜰 마트 추천 목록 정리해봤습니다. #도쿄 #장보기 #알뜰', 'ko', DATE_SUB(NOW(), INTERVAL 1 HOUR), DATE_SUB(NOW(), INTERVAL 1 HOUR)),
(4, 3, 3, '新宿ドンキでお菓子と化粧品のまとめ買い同行者募集します！ #新宿 #ドンキ #買い物', 'ja', DATE_SUB(NOW(), INTERVAL 2 HOUR), DATE_SUB(NOW(), INTERVAL 2 HOUR)),
(5, 4, 4, '大阪難波のライフスーパーで夕方の割引刺身買いました。最高！ #大阪 #スーパー #割引', 'ja', DATE_SUB(NOW(), INTERVAL 1 HOUR), DATE_SUB(NOW(), INTERVAL 1 HOUR));

-- 5. Community Comments (댓글)
INSERT INTO community_comments (id, post_id, author_id, content, locale, created_at, updated_at) VALUES
(1, 1, 2, '오 대박이네요! 저도 소고기 소분 파티 신청했습니다 ㅎㅎ', 'ko', DATE_SUB(NOW(), INTERVAL 150 MINUTE), DATE_SUB(NOW(), INTERVAL 150 MINUTE)),
(2, 1, 3, '양재점 주차 아직 붐비나요?', 'ko', DATE_SUB(NOW(), INTERVAL 130 MINUTE), DATE_SUB(NOW(), INTERVAL 130 MINUTE)),
(3, 2, 1, '좋은 정보 감사합니다! 오늘퇴근길에 들러봐야겠네요.', 'ko', DATE_SUB(NOW(), INTERVAL 90 MINUTE), DATE_SUB(NOW(), INTERVAL 90 MINUTE)),
(4, 4, 4, '一緒に行きたいです！時間の調整可能でしょうか？', 'ja', DATE_SUB(NOW(), INTERVAL 60 MINUTE), DATE_SUB(NOW(), INTERVAL 60 MINUTE));

-- 6. Community Post Likes (좋아요)
INSERT INTO community_post_likes (id, user_id, post_id, created_at) VALUES
(1, 2, 1, NOW()),
(2, 3, 1, NOW()),
(3, 1, 2, NOW()),
(4, 1, 3, NOW()),
(5, 2, 3, NOW()),
(6, 4, 4, NOW());

-- 7. Chat Messages (채팅)
INSERT INTO chat_messages (id, party_id, sender_id, content, message_type, created_at) VALUES
(1, 1, 1, '안녕하세요! 소고기 소분 모임에 오신 걸 환영합니다.', 'TALK', DATE_SUB(NOW(), INTERVAL 30 MINUTE)),
(2, 1, 2, '안녕하세요 코끼리님! 3시 정문 앞에서 뵈면 될까요?', 'TALK', DATE_SUB(NOW(), INTERVAL 20 MINUTE)),
(3, 1, 1, '네 맞습니다! 지퍼백이랑 보냉백 챙겨갈게요~', 'TALK', DATE_SUB(NOW(), INTERVAL 10 MINUTE));
