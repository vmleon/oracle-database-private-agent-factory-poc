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
    frontend = { ip = module.frontend.private_ip, port = 80 }
    backend  = { ip = module.backend.private_ip, port = 8090 }
    paf      = { ip = module.paf.private_ip, port = 8080 }
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
}

resource "oci_load_balancer_backend" "this" {
  for_each = local.backends

  load_balancer_id = oci_load_balancer_load_balancer.lb.id
  backendset_name  = oci_load_balancer_backend_set.this[each.key].name
  ip_address       = each.value.ip
  port             = each.value.port
}

resource "oci_load_balancer_listener" "http" {
  load_balancer_id         = oci_load_balancer_load_balancer.lb.id
  name                     = "http"
  default_backend_set_name = oci_load_balancer_backend_set.this["frontend"].name
  port                     = 80
  protocol                 = "HTTP"

  path_route_set_name = oci_load_balancer_path_route_set.routes.name
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
