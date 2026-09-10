# Public entry point. Paths mirror the local Caddy proxy so the same URLs work
# on both targets: the UIs on /mobile and /backoffice, the API on /api, and the
# PAF console on /agentFactory.
resource "oci_load_balancer_load_balancer" "lb" {
  compartment_id = var.compartment_ocid
  display_name   = "${var.label}-lb"
  shape          = "flexible"
  subnet_ids     = [oci_core_subnet.public.id]
  is_private     = false

  shape_details {
    minimum_bandwidth_in_mbps = 10
    maximum_bandwidth_in_mbps = 100
  }
}

locals {
  backends = {
    frontend = { ip = module.frontend.private_ip, port = 80, ssl = false }
    backend  = { ip = module.backend.private_ip, port = 8090, ssl = false }
    # PAF terminates TLS itself, with a self-signed certificate.
    paf = { ip = module.paf.private_ip, port = 8080, ssl = true }
  }
}

resource "oci_load_balancer_backend_set" "this" {
  for_each = local.backends

  load_balancer_id = oci_load_balancer_load_balancer.lb.id
  name             = each.key
  policy           = "ROUND_ROBIN"

  health_checker {
    protocol = "TCP"
    port     = each.value.port
  }

  # PAF generates its own self-signed certificate during its install wizard,
  # which runs after this stack exists — so there is no CA to upload and trust
  # at apply time, and peer verification cannot be switched on here yet. The
  # hop is encrypted but unverified: anything already inside the VCN could
  # impersonate PAF to the load balancer. Tracked in BACKLOG.md.
  dynamic "ssl_configuration" {
    for_each = each.value.ssl ? [1] : []
    content {
      verify_peer_certificate = false
    }
  }
}

resource "oci_load_balancer_backend" "this" {
  for_each = local.backends

  load_balancer_id = oci_load_balancer_load_balancer.lb.id
  backendset_name  = oci_load_balancer_backend_set.this[each.key].name
  ip_address       = each.value.ip
  port             = each.value.port
}

# TLS terminates here. OCI expresses that as an HTTP listener carrying an
# ssl_configuration, not as a "HTTPS" protocol.
resource "oci_load_balancer_listener" "https" {
  load_balancer_id         = oci_load_balancer_load_balancer.lb.id
  name                     = "https"
  default_backend_set_name = oci_load_balancer_backend_set.this["frontend"].name
  port                     = 443
  protocol                 = "HTTP"

  path_route_set_name = oci_load_balancer_path_route_set.routes.name

  # `verify_peer_certificate` means different things in the two places it
  # appears. On a listener it asks the load balancer to require and validate a
  # certificate from the *client* — mutual TLS. Public browsers present none, and
  # leaving it at its `true` default makes the API reject the bundle for having
  # no CA to validate against. On a backend set, further up, the same field
  # governs whether the load balancer validates the *backend's* certificate.
  ssl_configuration {
    certificate_name        = oci_load_balancer_certificate.lb.certificate_name
    verify_peer_certificate = false
  }
}

# Port 80 exists only to send callers to 443, so nothing is served in the clear.
resource "oci_load_balancer_rule_set" "redirect_to_https" {
  load_balancer_id = oci_load_balancer_load_balancer.lb.id
  name             = "redirecttohttps"

  items {
    action        = "REDIRECT"
    response_code = 301

    conditions {
      attribute_name  = "PATH"
      attribute_value = "/"
      operator        = "FORCE_LONGEST_PREFIX_MATCH"
    }

    redirect_uri {
      protocol = "HTTPS"
      host     = "{host}"
      port     = 443
      path     = "{path}"
      query    = "{query}"
    }
  }
}

resource "oci_load_balancer_listener" "http_redirect" {
  load_balancer_id         = oci_load_balancer_load_balancer.lb.id
  name                     = "http"
  default_backend_set_name = oci_load_balancer_backend_set.this["frontend"].name
  port                     = 80
  protocol                 = "HTTP"

  rule_set_names = [oci_load_balancer_rule_set.redirect_to_https.name]
}

# Mirrors the local Caddy front door so both targets serve the same URLs:
# /v1 to the API, /agentFactory to PAF, and everything else to the customer SPA
# at the root, which is where its asset paths expect it.
resource "oci_load_balancer_path_route_set" "routes" {
  load_balancer_id = oci_load_balancer_load_balancer.lb.id
  name             = "routes"

  path_routes {
    path             = "/v1"
    backend_set_name = oci_load_balancer_backend_set.this["backend"].name
    path_match_type {
      match_type = "PREFIX_MATCH"
    }
  }

  path_routes {
    path             = "/agentFactory"
    backend_set_name = oci_load_balancer_backend_set.this["paf"].name
    path_match_type {
      match_type = "PREFIX_MATCH"
    }
  }
}
