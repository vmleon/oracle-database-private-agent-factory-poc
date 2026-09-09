variable "compartment_ocid" {
  description = "Compartment the instance is created in."
  type        = string
}

variable "tier_name" {
  description = "One of ops, frontend, backend, paf."
  type        = string

  validation {
    condition     = contains(["ops", "frontend", "backend", "paf"], var.tier_name)
    error_message = "tier_name must be one of ops, frontend, backend, paf."
  }
}

variable "service_name" {
  description = "Prefix for the systemd unit, log, and state paths."
  type        = string
}

variable "project_name" {
  description = "Kebab-case project name."
  type        = string
}

variable "deploy_id" {
  description = "Random suffix keeping globally-unique names distinct."
  type        = string
}

variable "subnet_id" {
  description = "Subnet the instance attaches to."
  type        = string
}

variable "assign_public_ip" {
  description = "True only for tiers in the public subnet."
  type        = bool
  default     = false
}

variable "ssh_public_key" {
  description = "Public key installed for the opc user."
  type        = string
}

variable "artifact_par_url" {
  description = "Read-only PAR the instance curls its payload from."
  type        = string
  sensitive   = true
}

variable "ansible_params" {
  description = "Values written to /home/opc/ansible_params.json for the playbook."
  type        = map(string)
  default     = {}
  sensitive   = true
}

variable "instance_shape" {
  description = "Compute shape."
  type        = string
  default     = "VM.Standard.E5.Flex"
}

variable "instance_ocpus" {
  description = "OCPUs for the flexible shape."
  type        = number
  default     = 2
}

variable "instance_memory_gbs" {
  description = "Memory for the flexible shape."
  type        = number
  default     = 16
}

variable "ads" {
  description = "Availability domains from the tenancy data source."
  type        = list(any)
}

variable "region" {
  description = "Region identifier, used to reach the regional yum endpoint."
  type        = string
}
