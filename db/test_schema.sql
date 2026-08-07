-- Repeatable MySQL contract assertions. All test data is rolled back.
-- The application user needs DML, EXECUTE, CREATE ROUTINE, and ALTER ROUTINE
-- on DreamEscapes; db/setup_mysql.sh grants that database-scoped access.
USE `DreamEscapes`;

DELIMITER $$
DROP PROCEDURE IF EXISTS `RunDreamEscapesDatabaseTests`$$
CREATE PROCEDURE `RunDreamEscapesDatabaseTests`()
BEGIN
  DECLARE v_user_id BIGINT UNSIGNED;
  DECLARE v_other_user_id BIGINT UNSIGNED;
  DECLARE v_bucket_id BIGINT UNSIGNED;
  DECLARE v_destination_id BIGINT UNSIGNED;
  DECLARE v_review_id BIGINT UNSIGNED;
  DECLARE v_post_id BIGINT UNSIGNED;
  DECLARE v_duplicate_rejected BOOLEAN DEFAULT FALSE;
  DECLARE v_count INT DEFAULT 0;

  INSERT INTO users (username, email, password_hash)
  VALUES (
    'Schema Test User',
    CONCAT('schema-test-', UUID(), '@example.com'),
    '$2b$12$oxAecb3Pzp6iNyu4R5IkZ.MoDiMjZFQfsk9ejoWeQ03zwOC8V.296'
  );
  SET v_user_id = LAST_INSERT_ID();

  INSERT INTO users (username, email, password_hash)
  VALUES (
    'Other Test User',
    CONCAT('schema-other-', UUID(), '@example.com'),
    '$2b$12$oxAecb3Pzp6iNyu4R5IkZ.MoDiMjZFQfsk9ejoWeQ03zwOC8V.296'
  );
  SET v_other_user_id = LAST_INSERT_ID();

  BEGIN
    DECLARE CONTINUE HANDLER FOR 1062 SET v_duplicate_rejected = TRUE;
    INSERT INTO users (username, email, password_hash)
    SELECT 'Duplicate', email,
           '$2b$12$oxAecb3Pzp6iNyu4R5IkZ.MoDiMjZFQfsk9ejoWeQ03zwOC8V.296'
    FROM users WHERE user_id = v_user_id;
  END;
  IF NOT v_duplicate_rejected THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Duplicate email was not rejected';
  END IF;

  INSERT INTO bucket_list_destinations (
    user_id, destination_name, city, country, categories, latitude, longitude,
    place_id
  ) VALUES (
    v_user_id, 'Test Destination', 'Newark', 'United States', 'culture',
    40.7357000, -74.1724000, 'schema-test-place'
  );
  SET v_bucket_id = LAST_INSERT_ID();

  SELECT COUNT(*) INTO v_count FROM bucket_list_destinations
  WHERE bucket_item_id = v_bucket_id AND user_id = v_other_user_id;
  IF v_count <> 0 THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Ownership filter leaked an item';
  END IF;

  SET v_duplicate_rejected = FALSE;
  BEGIN
    DECLARE CONTINUE HANDLER FOR 1062 SET v_duplicate_rejected = TRUE;
    INSERT INTO bucket_list_destinations (
      user_id, destination_name, city, country, categories, latitude, longitude,
      place_id
    ) VALUES (
      v_user_id, 'Duplicate Destination', 'Newark', 'United States', 'culture',
      40.7357000, -74.1724000, 'schema-test-place'
    );
  END;
  IF NOT v_duplicate_rejected THEN
    SIGNAL SQLSTATE '45000'
      SET MESSAGE_TEXT = 'Duplicate bucket-list item was not rejected';
  END IF;

  INSERT INTO destination_cache (
    cache_key, place_id, normalized_query, country, categories, attraction_type,
    destination_name, destination_description, attractions, nearby_attractions,
    formatted_address, payload, raw_api_response, cached_at, expires_at
  ) VALUES (
    CONCAT('schema-test-', UUID()), 'schema-cache-place', 'newark',
    'united states', 'culture', 'museum', 'Test Cache', 'Test cache row',
    JSON_ARRAY(), JSON_ARRAY(), 'Newark, NJ', JSON_OBJECT(), JSON_OBJECT(),
    CURRENT_TIMESTAMP(6), DATE_ADD(CURRENT_TIMESTAMP(6), INTERVAL 24 HOUR)
  );
  SELECT COUNT(*) INTO v_count FROM destination_cache
  WHERE place_id = 'schema-cache-place' AND expires_at > CURRENT_TIMESTAMP(6);
  IF v_count <> 1 THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Fresh cache lookup failed';
  END IF;

  UPDATE destination_cache
  SET cached_at = DATE_SUB(CURRENT_TIMESTAMP(6), INTERVAL 25 HOUR),
      expires_at = DATE_SUB(CURRENT_TIMESTAMP(6), INTERVAL 1 HOUR)
  WHERE place_id = 'schema-cache-place';
  SELECT COUNT(*) INTO v_count FROM destination_cache
  WHERE place_id = 'schema-cache-place' AND expires_at > CURRENT_TIMESTAMP(6);
  IF v_count <> 0 THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Cache did not expire';
  END IF;

  INSERT INTO search_history (user_id, query)
  VALUES (v_user_id, 'Newark museums');
  SELECT COUNT(*) INTO v_count FROM search_history WHERE user_id = v_user_id;
  IF v_count <> 1 THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Search history was not saved';
  END IF;

  UPDATE users SET role = 'admin' WHERE user_id = v_user_id;
  INSERT INTO admin_audit_logs (
    admin_user_id, action_type, target_type, target_id, notes
  ) VALUES (
    v_user_id, 'schema_test', 'user', v_other_user_id, 'Audit assertion'
  );
  SELECT COUNT(*) INTO v_count FROM admin_audit_logs
  WHERE admin_user_id = v_user_id;
  IF v_count <> 1 THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Admin audit was not saved';
  END IF;

  INSERT INTO destinations (
    place_id, destination_name, city, country, formatted_address
  ) VALUES (
    CONCAT('schema-review-place-', UUID()), 'Review Destination', 'Newark',
    'United States', 'Newark, NJ'
  );
  SET v_destination_id = LAST_INSERT_ID();
  INSERT INTO destination_reviews (user_id, destination_id, comment, rating)
  VALUES (v_user_id, v_destination_id, 'A persisted schema review.', 5);
  SET v_review_id = LAST_INSERT_ID();
  SELECT COUNT(*) INTO v_count FROM destination_reviews
  WHERE review_id = v_review_id AND user_id = v_user_id
    AND destination_id = v_destination_id AND rating = 5;
  IF v_count <> 1 THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Destination review was not saved';
  END IF;

  INSERT INTO community_posts (
    author_user_id, post_type, title, body, destination_name, picture_url
  ) VALUES (
    v_user_id, 'experience', 'Schema community post',
    'This is persisted community post text for the schema test.',
    'Newark', 'https://example.com/newark.jpg'
  );
  SET v_post_id = LAST_INSERT_ID();
  SELECT COUNT(*) INTO v_count FROM community_posts
  WHERE post_id = v_post_id AND author_user_id = v_user_id
    AND body LIKE '%community post text%';
  IF v_count <> 1 THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Community post was not saved';
  END IF;

  SELECT 'All DreamEscapes database assertions passed.' AS result;
END$$
DELIMITER ;

START TRANSACTION;
CALL RunDreamEscapesDatabaseTests();
ROLLBACK;
DROP PROCEDURE `RunDreamEscapesDatabaseTests`;
