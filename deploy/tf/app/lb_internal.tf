# TLS gateway for the MCP wrappers. PAF refuses plain-http MCP URLs, so
# something has to terminate TLS in front of them; this is the managed
# equivalent of the Caddy proxy the local target runs.
#
# One listener per wrapper rather than one listener with path routes: an OCI
# load balancer cannot rewrite a path, so a prefix like /banking/mcp would reach
# the wrapper unchanged and 404. Giving each its own port leaves the path
# untouched, which also removes the two workarounds the local proxy needs — the
# prefix strip and the trailing-slash fix that stops a 307 breaking the
# handshake.
resource "oci_load_balancer_load_balancer" "internal" {
  compartment_id = var.compartment_ocid
  display_name   = "${var.label}-lb-internal"
  shape          = "flexible"
  subnet_ids     = [oci_core_subnet.private.id]
  is_private     = true

  shape_details {
    minimum_bandwidth_in_mbps = 10
    maximum_bandwidth_in_mbps = 100
  }
}

resource "tls_private_key" "mcp" {
  algorithm = "RSA"
  rsa_bits  = 2048
}

resource "tls_self_signed_cert" "mcp" {
  private_key_pem = tls_private_key.mcp.private_key_pem

  subject {
    common_name  = "${var.label}-mcp"
    organization = var.label
  }

  ip_addresses          = [oci_load_balancer_load_balancer.internal.ip_address_details[0].ip_address]
  validity_period_hours = 8760
  early_renewal_hours   = 720

  allowed_uses = ["key_encipherment", "digital_signature", "server_auth"]
}

resource "oci_load_balancer_certificate" "mcp" {
  load_balancer_id   = oci_load_balancer_load_balancer.internal.id
  certificate_name   = "${var.label}-mcp-${substr(sha256(tls_self_signed_cert.mcp.cert_pem), 0, 8)}"
  private_key        = tls_private_key.mcp.private_key_pem
  public_certificate = tls_self_signed_cert.mcp.cert_pem

  lifecycle {
    create_before_destroy = true
  }
}

locals {
  # Port per wrapper, matching the ports they listen on locally so the flow's
  # server URLs differ only in host.
  mcp_ports = {
    banking     = 8503
    application = 8504
    research    = 8505
  }
}

resource "oci_load_balancer_backend_set" "mcp" {
  for_each = local.mcp_ports

  load_balancer_id = oci_load_balancer_load_balancer.internal.id
  name             = each.key
  policy           = "ROUND_ROBIN"

  health_checker {
    protocol = "TCP"
    port     = each.value
  }
}

resource "oci_load_balancer_backend" "mcp" {
  for_each = local.mcp_ports

  load_balancer_id = oci_load_balancer_load_balancer.internal.id
  backendset_name  = oci_load_balancer_backend_set.mcp[each.key].name
  ip_address       = module.backend.private_ip
  port             = each.value
}

resource "oci_load_balancer_listener" "mcp" {
  for_each = local.mcp_ports

  load_balancer_id         = oci_load_balancer_load_balancer.internal.id
  name                     = each.key
  default_backend_set_name = oci_load_balancer_backend_set.mcp[each.key].name
  port                     = each.value
  protocol                 = "HTTP"

  ssl_configuration {
    certificate_name        = oci_load_balancer_certificate.mcp.certificate_name
    verify_peer_certificate = false
  }

  # An MCP call can sit silent while the agent thinks. The 60-second default
  # would drop the connection mid-turn.
  connection_configuration {
    idle_timeout_in_seconds = 300
  }
}

# PAF verifies MCP TLS against its administrator certificate store, so the
# certificate has to reach the operator as a file to upload.
resource "local_file" "mcp_ca" {
  filename = "${path.module}/generated/mcp-ca.pem"
  content  = tls_self_signed_cert.mcp.cert_pem
}
