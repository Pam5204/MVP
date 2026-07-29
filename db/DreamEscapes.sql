-- DreamEscapes MySQL 8 schema and stored-procedure contract.
-- Application credentials are created by setup_mysql.sh, never in this file.

CREATE DATABASE IF NOT EXISTS `DreamEscapes`
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;
USE `DreamEscapes`;

CREATE TABLE IF NOT EXISTS `users` (
  `user_id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `username` VARCHAR(100) NOT NULL,
  `email` VARCHAR(255) NOT NULL,
  `password_hash` VARCHAR(255) NOT NULL,
  `role` ENUM('user', 'admin') NOT NULL DEFAULT 'user',
  `travel_preferences` TEXT NOT NULL DEFAULT (''),
  `account_status` ENUM('enabled', 'disabled') NOT NULL DEFAULT 'enabled',
  `last_login_at` DATETIME(6) NULL,
  `created_at` DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  `updated_at` DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
    ON UPDATE CURRENT_TIMESTAMP(6),
  PRIMARY KEY (`user_id`),
  UNIQUE KEY `uq_users_email` (`email`),
  KEY `idx_users_role` (`role`),
  KEY `idx_users_status` (`account_status`)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS `bucket_list_destinations` (
  `bucket_item_id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `user_id` BIGINT UNSIGNED NOT NULL,
  `destination_name` VARCHAR(255) NOT NULL,
  `city` VARCHAR(150) NOT NULL,
  `country` VARCHAR(150) NOT NULL,
  `categories` TEXT NOT NULL,
  `latitude` DECIMAL(10,7) NOT NULL,
  `longitude` DECIMAL(10,7) NOT NULL,
  `place_id` VARCHAR(255) NOT NULL,
  `travel_type_label` VARCHAR(100) NOT NULL DEFAULT '',
  `saved_at` DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  `updated_at` DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
    ON UPDATE CURRENT_TIMESTAMP(6),
  PRIMARY KEY (`bucket_item_id`),
  UNIQUE KEY `uq_bucket_user_place` (`user_id`, `place_id`),
  KEY `idx_bucket_user` (`user_id`),
  KEY `idx_bucket_place` (`place_id`),
  KEY `idx_bucket_country` (`country`),
  KEY `idx_bucket_categories` (`categories`(191)),
  CONSTRAINT `fk_bucket_user`
    FOREIGN KEY (`user_id`) REFERENCES `users` (`user_id`) ON DELETE CASCADE
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS `destination_cache` (
  `cache_id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `cache_key` VARCHAR(128) NOT NULL,
  `place_id` VARCHAR(255) NOT NULL DEFAULT '',
  `normalized_query` VARCHAR(255) NOT NULL DEFAULT '',
  `country` VARCHAR(150) NOT NULL DEFAULT '',
  `categories` VARCHAR(500) NOT NULL DEFAULT '',
  `attraction_type` VARCHAR(100) NOT NULL DEFAULT '',
  `latitude` DECIMAL(10,7) NULL,
  `longitude` DECIMAL(10,7) NULL,
  `destination_name` VARCHAR(255) NOT NULL DEFAULT '',
  `destination_description` TEXT NOT NULL,
  `attractions` JSON NOT NULL,
  `nearby_attractions` JSON NOT NULL,
  `formatted_address` TEXT NOT NULL,
  `payload` JSON NOT NULL,
  `raw_api_response` JSON NOT NULL,
  `source_api` VARCHAR(50) NOT NULL DEFAULT 'Geoapify',
  `cached_at` DATETIME(6) NOT NULL,
  `expires_at` DATETIME(6) NOT NULL,
  `updated_at` DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
    ON UPDATE CURRENT_TIMESTAMP(6),
  PRIMARY KEY (`cache_id`),
  UNIQUE KEY `uq_cache_key` (`cache_key`),
  KEY `idx_cache_place` (`place_id`),
  KEY `idx_cache_query` (`normalized_query`),
  KEY `idx_cache_country` (`country`),
  KEY `idx_cache_categories` (`categories`(191)),
  KEY `idx_cache_expires` (`expires_at`)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS `search_history` (
  `search_id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `user_id` BIGINT UNSIGNED NULL,
  `query` VARCHAR(255) NOT NULL,
  `country_filter` VARCHAR(150) NOT NULL DEFAULT '',
  `category_filter` VARCHAR(255) NOT NULL DEFAULT '',
  `attraction_type_filter` VARCHAR(100) NOT NULL DEFAULT '',
  `place_id` VARCHAR(255) NOT NULL DEFAULT '',
  `created_at` DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  PRIMARY KEY (`search_id`),
  KEY `idx_history_user` (`user_id`),
  KEY `idx_history_created` (`created_at`),
  CONSTRAINT `fk_history_user`
    FOREIGN KEY (`user_id`) REFERENCES `users` (`user_id`) ON DELETE CASCADE
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS `admin_audit_logs` (
  `audit_id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `admin_user_id` BIGINT UNSIGNED NOT NULL,
  `action_type` VARCHAR(100) NOT NULL,
  `target_type` VARCHAR(100) NOT NULL,
  `target_id` VARCHAR(255) NOT NULL DEFAULT '',
  `created_at` DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  `notes` TEXT NOT NULL,
  `status` VARCHAR(50) NOT NULL DEFAULT 'success',
  PRIMARY KEY (`audit_id`),
  KEY `idx_audit_admin` (`admin_user_id`),
  KEY `idx_audit_created` (`created_at`),
  CONSTRAINT `fk_audit_admin`
    FOREIGN KEY (`admin_user_id`) REFERENCES `users` (`user_id`) ON DELETE RESTRICT
) ENGINE=InnoDB;

DELIMITER $$

DROP PROCEDURE IF EXISTS `RegisterUser`$$
CREATE PROCEDURE `RegisterUser`(
  IN p_username VARCHAR(100),
  IN p_email VARCHAR(255),
  IN p_password_hash VARCHAR(255)
)
BEGIN
  INSERT INTO users (username, email, password_hash)
  VALUES (p_username, LOWER(TRIM(p_email)), p_password_hash);
  SELECT user_id, username, email, role, account_status, created_at
  FROM users WHERE user_id = LAST_INSERT_ID();
END$$

DROP PROCEDURE IF EXISTS `FindUserByEmail`$$
CREATE PROCEDURE `FindUserByEmail`(IN p_email VARCHAR(255))
BEGIN
  SELECT user_id, username, email, password_hash, role, travel_preferences,
         account_status, last_login_at, created_at, updated_at
  FROM users WHERE email = LOWER(TRIM(p_email)) LIMIT 1;
END$$

DROP PROCEDURE IF EXISTS `UpdateLastLogin`$$
CREATE PROCEDURE `UpdateLastLogin`(IN p_user_id BIGINT UNSIGNED)
BEGIN
  UPDATE users SET last_login_at = CURRENT_TIMESTAMP(6)
  WHERE user_id = p_user_id AND account_status = 'enabled';
END$$

DROP PROCEDURE IF EXISTS `UpdateProfile`$$
CREATE PROCEDURE `UpdateProfile`(
  IN p_user_id BIGINT UNSIGNED,
  IN p_username VARCHAR(100),
  IN p_email VARCHAR(255),
  IN p_password_hash VARCHAR(255)
)
BEGIN
  UPDATE users
  SET username = p_username,
      email = LOWER(TRIM(p_email)),
      password_hash = COALESCE(NULLIF(p_password_hash, ''), password_hash)
  WHERE user_id = p_user_id;
  SELECT user_id, username, email, role, travel_preferences, account_status,
         last_login_at, created_at, updated_at
  FROM users WHERE user_id = p_user_id;
END$$

DROP PROCEDURE IF EXISTS `UpdateTravelPreferences`$$
CREATE PROCEDURE `UpdateTravelPreferences`(
  IN p_user_id BIGINT UNSIGNED,
  IN p_preferences TEXT
)
BEGIN
  UPDATE users SET travel_preferences = COALESCE(p_preferences, '')
  WHERE user_id = p_user_id;
END$$

DROP PROCEDURE IF EXISTS `GetBucketListByUserId`$$
CREATE PROCEDURE `GetBucketListByUserId`(IN p_user_id BIGINT UNSIGNED)
BEGIN
  SELECT * FROM bucket_list_destinations
  WHERE user_id = p_user_id ORDER BY saved_at DESC;
END$$

DROP PROCEDURE IF EXISTS `AddBucketListItem`$$
CREATE PROCEDURE `AddBucketListItem`(
  IN p_user_id BIGINT UNSIGNED,
  IN p_destination_name VARCHAR(255),
  IN p_city VARCHAR(150),
  IN p_country VARCHAR(150),
  IN p_categories TEXT,
  IN p_latitude DECIMAL(10,7),
  IN p_longitude DECIMAL(10,7),
  IN p_place_id VARCHAR(255),
  IN p_travel_type_label VARCHAR(100)
)
BEGIN
  INSERT INTO bucket_list_destinations (
    user_id, destination_name, city, country, categories, latitude, longitude,
    place_id, travel_type_label
  ) VALUES (
    p_user_id, p_destination_name, p_city, p_country, COALESCE(p_categories, ''),
    p_latitude, p_longitude, p_place_id, COALESCE(p_travel_type_label, '')
  );
  SELECT * FROM bucket_list_destinations
  WHERE bucket_item_id = LAST_INSERT_ID();
END$$

DROP PROCEDURE IF EXISTS `CheckDuplicateBucketListItem`$$
CREATE PROCEDURE `CheckDuplicateBucketListItem`(
  IN p_user_id BIGINT UNSIGNED,
  IN p_place_id VARCHAR(255)
)
BEGIN
  SELECT EXISTS(
    SELECT 1 FROM bucket_list_destinations
    WHERE user_id = p_user_id AND place_id = p_place_id
  ) AS is_duplicate;
END$$

DROP PROCEDURE IF EXISTS `UpdateBucketListCategoryTravelLabel`$$
CREATE PROCEDURE `UpdateBucketListCategoryTravelLabel`(
  IN p_bucket_item_id BIGINT UNSIGNED,
  IN p_user_id BIGINT UNSIGNED,
  IN p_categories TEXT,
  IN p_travel_type_label VARCHAR(100)
)
BEGIN
  UPDATE bucket_list_destinations
  SET categories = COALESCE(p_categories, categories),
      travel_type_label = COALESCE(p_travel_type_label, travel_type_label)
  WHERE bucket_item_id = p_bucket_item_id AND user_id = p_user_id;
  SELECT ROW_COUNT() AS affected_rows;
END$$

DROP PROCEDURE IF EXISTS `DeleteBucketListItem`$$
CREATE PROCEDURE `DeleteBucketListItem`(
  IN p_bucket_item_id BIGINT UNSIGNED,
  IN p_user_id BIGINT UNSIGNED
)
BEGIN
  DELETE FROM bucket_list_destinations
  WHERE bucket_item_id = p_bucket_item_id AND user_id = p_user_id;
  SELECT ROW_COUNT() AS affected_rows;
END$$

DROP PROCEDURE IF EXISTS `GetFreshDestinationCache`$$
CREATE PROCEDURE `GetFreshDestinationCache`(IN p_cache_key VARCHAR(128))
BEGIN
  SELECT * FROM destination_cache
  WHERE cache_key = p_cache_key AND expires_at > CURRENT_TIMESTAMP(6)
  LIMIT 1;
END$$

DROP PROCEDURE IF EXISTS `GetStaleDestinationCache`$$
CREATE PROCEDURE `GetStaleDestinationCache`(IN p_cache_key VARCHAR(128))
BEGIN
  SELECT * FROM destination_cache
  WHERE cache_key = p_cache_key
  LIMIT 1;
END$$

DROP PROCEDURE IF EXISTS `UpsertDestinationCache`$$
CREATE PROCEDURE `UpsertDestinationCache`(
  IN p_cache_key VARCHAR(128),
  IN p_place_id VARCHAR(255),
  IN p_normalized_query VARCHAR(255),
  IN p_country VARCHAR(150),
  IN p_categories VARCHAR(500),
  IN p_attraction_type VARCHAR(100),
  IN p_latitude DECIMAL(10,7),
  IN p_longitude DECIMAL(10,7),
  IN p_destination_name VARCHAR(255),
  IN p_destination_description TEXT,
  IN p_attractions JSON,
  IN p_nearby_attractions JSON,
  IN p_formatted_address TEXT,
  IN p_payload JSON,
  IN p_raw_api_response JSON
)
BEGIN
  INSERT INTO destination_cache (
    cache_key, place_id, normalized_query, country, categories, attraction_type,
    latitude, longitude, destination_name, destination_description, attractions,
    nearby_attractions, formatted_address, payload, raw_api_response, cached_at,
    expires_at
  ) VALUES (
    p_cache_key, COALESCE(p_place_id, ''), COALESCE(p_normalized_query, ''),
    COALESCE(p_country, ''), COALESCE(p_categories, ''),
    COALESCE(p_attraction_type, ''), p_latitude, p_longitude,
    COALESCE(p_destination_name, ''), COALESCE(p_destination_description, ''),
    COALESCE(p_attractions, JSON_ARRAY()),
    COALESCE(p_nearby_attractions, JSON_ARRAY()),
    COALESCE(p_formatted_address, ''), COALESCE(p_payload, JSON_OBJECT()),
    COALESCE(p_raw_api_response, JSON_OBJECT()), CURRENT_TIMESTAMP(6),
    DATE_ADD(CURRENT_TIMESTAMP(6), INTERVAL 24 HOUR)
  )
  ON DUPLICATE KEY UPDATE
    place_id = VALUES(place_id),
    normalized_query = VALUES(normalized_query),
    country = VALUES(country),
    categories = VALUES(categories),
    attraction_type = VALUES(attraction_type),
    latitude = VALUES(latitude),
    longitude = VALUES(longitude),
    destination_name = VALUES(destination_name),
    destination_description = VALUES(destination_description),
    attractions = VALUES(attractions),
    nearby_attractions = VALUES(nearby_attractions),
    formatted_address = VALUES(formatted_address),
    payload = VALUES(payload),
    raw_api_response = VALUES(raw_api_response),
    cached_at = VALUES(cached_at),
    expires_at = VALUES(expires_at);
END$$

DROP PROCEDURE IF EXISTS `SaveSearchHistory`$$
CREATE PROCEDURE `SaveSearchHistory`(
  IN p_user_id BIGINT UNSIGNED,
  IN p_query VARCHAR(255),
  IN p_country_filter VARCHAR(150),
  IN p_category_filter VARCHAR(255),
  IN p_attraction_type_filter VARCHAR(100),
  IN p_place_id VARCHAR(255)
)
BEGIN
  INSERT INTO search_history (
    user_id, query, country_filter, category_filter, attraction_type_filter,
    place_id
  ) VALUES (
    p_user_id, p_query, COALESCE(p_country_filter, ''),
    COALESCE(p_category_filter, ''), COALESCE(p_attraction_type_filter, ''),
    COALESCE(p_place_id, '')
  );
END$$

DROP PROCEDURE IF EXISTS `GetRecentSearchHistory`$$
CREATE PROCEDURE `GetRecentSearchHistory`(
  IN p_user_id BIGINT UNSIGNED,
  IN p_limit INT
)
BEGIN
  SELECT * FROM search_history
  WHERE user_id = p_user_id
  ORDER BY created_at DESC
  LIMIT p_limit;
END$$

DROP PROCEDURE IF EXISTS `GetAllUsersForAdmin`$$
CREATE PROCEDURE `GetAllUsersForAdmin`()
BEGIN
  SELECT user_id, username, email, role, travel_preferences, account_status,
         last_login_at, created_at, updated_at
  FROM users ORDER BY user_id;
END$$

DROP PROCEDURE IF EXISTS `UpdateUserRole`$$
CREATE PROCEDURE `UpdateUserRole`(
  IN p_user_id BIGINT UNSIGNED,
  IN p_role VARCHAR(20)
)
BEGIN
  IF p_role NOT IN ('user', 'admin') THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Invalid user role';
  END IF;
  UPDATE users SET role = p_role WHERE user_id = p_user_id;
END$$

DROP PROCEDURE IF EXISTS `EnableOrDisableUserAccount`$$
CREATE PROCEDURE `EnableOrDisableUserAccount`(
  IN p_user_id BIGINT UNSIGNED,
  IN p_status VARCHAR(20)
)
BEGIN
  IF p_status NOT IN ('enabled', 'disabled') THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Invalid account status';
  END IF;
  UPDATE users SET account_status = p_status WHERE user_id = p_user_id;
END$$

DROP PROCEDURE IF EXISTS `GetCachedDestinationsForAdmin`$$
CREATE PROCEDURE `GetCachedDestinationsForAdmin`()
BEGIN
  SELECT cache_id, place_id, destination_name, country, categories,
         formatted_address, source_api, cached_at, expires_at, updated_at
  FROM destination_cache ORDER BY updated_at DESC;
END$$

DROP PROCEDURE IF EXISTS `InsertAdminAuditLog`$$
CREATE PROCEDURE `InsertAdminAuditLog`(
  IN p_admin_user_id BIGINT UNSIGNED,
  IN p_action_type VARCHAR(100),
  IN p_target_type VARCHAR(100),
  IN p_target_id VARCHAR(255),
  IN p_notes TEXT,
  IN p_status VARCHAR(50)
)
BEGIN
  INSERT INTO admin_audit_logs (
    admin_user_id, action_type, target_type, target_id, notes, status
  ) VALUES (
    p_admin_user_id, p_action_type, p_target_type, COALESCE(p_target_id, ''),
    COALESCE(p_notes, ''), COALESCE(p_status, 'success')
  );
END$$

DROP PROCEDURE IF EXISTS `GetAdminAuditLogs`$$
CREATE PROCEDURE `GetAdminAuditLogs`()
BEGIN
  SELECT a.*, u.email AS admin_email
  FROM admin_audit_logs a
  JOIN users u ON u.user_id = a.admin_user_id
  ORDER BY a.created_at DESC;
END$$

DELIMITER ;
