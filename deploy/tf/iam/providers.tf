terraform {
  required_version = ">= 1.5.0"

  required_providers {
    oci = {
      source  = "oracle/oci"
      version = "~> 6.0"
    }
  }
}

# Identity resources are always created in the tenancy's home region.
provider "oci" {
  config_file_profile = var.oci_profile
  region              = var.region
}
