-- Optional local/demo seed data.
-- Both demo accounts use: DreamEscapesDemo123!
USE `DreamEscapes`;

INSERT INTO users (
  username, email, password_hash, role, travel_preferences, account_status
) VALUES
  (
    'Demo Traveler',
    'traveler@example.com',
    '$2b$12$oxAecb3Pzp6iNyu4R5IkZ.MoDiMjZFQfsk9ejoWeQ03zwOC8V.296',
    'user',
    'Museums, beaches, and family-friendly trips',
    'enabled'
  ),
  (
    'Demo Administrator',
    'admin@example.com',
    '$2b$12$oxAecb3Pzp6iNyu4R5IkZ.MoDiMjZFQfsk9ejoWeQ03zwOC8V.296',
    'admin',
    'Destination review',
    'enabled'
  )
ON DUPLICATE KEY UPDATE
  username = VALUES(username),
  role = VALUES(role),
  travel_preferences = VALUES(travel_preferences),
  account_status = VALUES(account_status);
