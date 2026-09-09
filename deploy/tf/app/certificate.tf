# A self-signed certificate for the public listener. The deployment has no DNS
# name, so the certificate is issued for the load balancer's own address and a
# browser will warn on first visit — accepted for a demo. Replacing it with a
# real certificate means giving the deployment a hostname and issuing against
# that; nothing else here changes.
resource "tls_private_key" "lb" {
  algorithm = "RSA"
  rsa_bits  = 2048
}

resource "tls_self_signed_cert" "lb" {
  private_key_pem = tls_private_key.lb.private_key_pem

  subject {
    common_name  = var.label
    organization = var.label
  }

  # The address is only known once the load balancer exists, so the certificate
  # is issued after it and before the listener that presents it.
  ip_addresses = [oci_load_balancer_load_balancer.lb.ip_address_details[0].ip_address]

  validity_period_hours = 8760
  early_renewal_hours   = 720

  allowed_uses = [
    "key_encipherment",
    "digital_signature",
    "server_auth",
  ]
}

# Load balancer certificates are immutable: a change has to create the
# replacement before the listener stops referencing the old one, and the name
# has to differ. Both are handled here so rotation is a normal apply.
resource "oci_load_balancer_certificate" "lb" {
  load_balancer_id   = oci_load_balancer_load_balancer.lb.id
  certificate_name   = "${var.label}-${substr(sha256(tls_self_signed_cert.lb.cert_pem), 0, 8)}"
  private_key        = tls_private_key.lb.private_key_pem
  public_certificate = tls_self_signed_cert.lb.cert_pem

  lifecycle {
    create_before_destroy = true
  }
}
