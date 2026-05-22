// Ohya SEO Growth OS Neo4j graph constraints / target model v1
// Draft only. Do not run without Gary approval.

CREATE CONSTRAINT article_slug_unique IF NOT EXISTS
FOR (a:Article) REQUIRE a.slug IS UNIQUE;

CREATE CONSTRAINT entity_name_normalized_unique IF NOT EXISTS
FOR (e:Entity) REQUIRE e.name_normalized IS UNIQUE;

CREATE CONSTRAINT topic_name_normalized_unique IF NOT EXISTS
FOR (t:Topic) REQUIRE t.name_normalized IS UNIQUE;

CREATE CONSTRAINT topic_cluster_slug_unique IF NOT EXISTS
FOR (c:TopicCluster) REQUIRE c.slug IS UNIQUE;

CREATE CONSTRAINT service_slug_unique IF NOT EXISTS
FOR (s:Service) REQUIRE s.slug IS UNIQUE;

// Target labels:
// Article(slug, title, url, payload_post_id, content_type, status, canonical_id, last_synced_at)
// Entity(name, name_normalized, type, aliases, verified, importance, created_at, updated_at)
// Topic(name, name_normalized, topic_type, status, verified, created_at, updated_at)
// TopicCluster(name, slug, description, commercial_intent, status, created_at, updated_at)
// Service(name, slug, offer_type, url, status)

// Target relationships:
// (:Article)-[:MENTIONS {count, confidence, source, importance, first_seen_heading, extraction_version, verified}]->(:Entity)
// (:Article)-[:COVERS {confidence, importance, source, verified}]->(:Topic)
// (:Article)-[:LINKS_TO {anchor_text, source_heading, source_block_index, link_position, is_contextual, nofollow, target_status, first_seen_at, last_checked_at}]->(:Article)
// (:Article)-[:BELONGS_TO_CLUSTER {role, confidence}]->(:TopicCluster)
// (:Topic)-[:PART_OF_CLUSTER {confidence, source}]->(:TopicCluster)
// (:Article)-[:SUPPORTS_SERVICE {intent, strength}]->(:Service)
