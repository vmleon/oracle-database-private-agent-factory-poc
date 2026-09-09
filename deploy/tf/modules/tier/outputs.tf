output "id" {
  value = oci_core_instance.this.id
}

output "private_ip" {
  value = oci_core_instance.this.private_ip
}

output "public_ip" {
  value = oci_core_instance.this.public_ip
}
