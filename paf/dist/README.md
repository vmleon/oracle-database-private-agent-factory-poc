# PAF kit tarballs

Download the Private Agent Factory 26.7 kit from Oracle Software Delivery and
drop the tarball here. The files are ignored by git — only this README is tracked.

One tarball per CPU architecture, and the two deployment targets do not share one:

| Target                          | Architecture | Filename                                   |
| ------------------------------- | ------------ | ------------------------------------------ |
| Local (Apple Silicon podman)    | ARM64        | `oracle_agent_factory_ARM64_26.7.0.tar.gz` |
| Cloud (`VM.Standard.E5.Flex`)   | X86_64       | `oracle_agent_factory_X86_64_26.7.0.tar.gz` |

`manage.py setup local` and `manage.py setup cloud` each resolve `PAF_TARBALL`
to the tarball matching their target. On the cloud target Terraform uploads it
to Object Storage, and the `paf` tier fetches it through a read-only
pre-authenticated request — the instance never holds OCI credentials.
