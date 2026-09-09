terraform {
  required_version = ">= 1.5.0"

  required_providers {
    oci = {
      source  = "oracle/oci"
      version = "~> 6.0"
    }
    local = {
      source  = "hashicorp/local"
      version = "~> 2.4"
    }
    archive = {
      source  = "hashicorp/archive"
      version = "~> 2.8"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.9"
    }
    time = {
      source  = "hashicorp/time"
      version = "~> 0.14"
    }
    tls = {
      source  = "hashicorp/tls"
      version = "~> 4.0"
    }
  }
}

# Home-region provider: identity resources and the Generative AI service live
# in the region that hosts the models, which is not always the workload region.
provider "oci" {
  config_file_profile = var.oci_profile
  region              = var.region
}

provider "oci" {
  alias               = "genai"
  config_file_profile = var.oci_profile
  region              = var.genai_region
}
