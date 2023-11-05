import torch

from typing import List, Optional, Tuple
from pytorch3d.renderer.cameras import CamerasBase


# Volume renderer which integrates color and density along rays
# according to the equations defined in [Mildenhall et al. 2020]
class VolumeRenderer(torch.nn.Module):
    def __init__(
        self,
        cfg
    ):
        super().__init__()

        self._chunk_size = cfg.chunk_size
        self._white_background = cfg.white_background if 'white_background' in cfg else False

    def _compute_weights(
        self,
        deltas,
        rays_density: torch.Tensor,
        eps: float = 1e-10
    ):
        deltas=deltas.squeeze()
        rays_density=rays_density.squeeze()
        # print("delta size: ", deltas.shape)
        # print("rays size: ", rays_density.shape)
        alpha = 1 - torch.exp(-deltas * rays_density)
        T = torch.cumprod(1.0 - alpha + eps, -1)
        T = torch.roll(T, 1, -1)
        T[..., 0] = 1.0
        weights = T * alpha      
        # alpha = 1 - torch.exp(-deltas * rays_density)
        # Do volume rendering
        # TODO (1.5): Compute weight used for rendering from transmittance and alpha
        # weights = alpha * torch.cumprod(torch.cat([torch.ones((alpha.shape[0], 1)).cuda(), 1.-alpha + 1e-10], -1), -1)[:, :-1]
        return weights
    
    def _aggregate(
        self,
        weights: torch.Tensor,
        rays_feature: torch.Tensor
    ):
        # rays_feature = rays_feature.view(-1, weights.shape[1], 3)
        # TODO (1.5): Aggregate (weighted sum of) features using weights
        rays_feature = rays_feature.view(-1, weights.shape[1], 3)
        feature = torch.sum(weights.unsqueeze(-1) * rays_feature, dim=1)
        

        return feature

    def forward(
        self,
        sampler,
        implicit_fn,
        ray_bundle,
    ):
        B = ray_bundle.shape[0]

        # Process the chunks of rays.
        chunk_outputs = []

        for chunk_start in range(0, B, self._chunk_size):
            cur_ray_bundle = ray_bundle[chunk_start:chunk_start+self._chunk_size]

            # Sample points along the ray
            cur_ray_bundle = sampler(cur_ray_bundle)
            n_pts = cur_ray_bundle.sample_shape[1]

            # Call implicit function with sample points
            implicit_output = implicit_fn(cur_ray_bundle)
            density = implicit_output['density']
            feature = implicit_output['feature']

            # Compute length of each ray segment
            depth_values = cur_ray_bundle.sample_lengths[..., 0]
            deltas = torch.cat(
                (
                    depth_values[..., 1:] - depth_values[..., :-1],
                    1e10 * torch.ones_like(depth_values[..., :1]),
                ),
                dim=-1,
            )[..., None]

            # Compute aggregation weights
            weights = self._compute_weights(
                deltas.view(-1, n_pts, 1),
                density.view(-1, n_pts, 1)
            ) 

            # TODO (1.5): Render (color) features using weights
            # print("Shape of weights",weights.shape)
            # print("Shape of feature",feature.shape)
            rgb_feature = self._aggregate(weights, feature)

            # TODO (1.5): Render depth map
            expanded_depth_values = depth_values.unsqueeze(-1).expand(-1, -1, feature.shape[-1])
            depth = self._aggregate(weights, expanded_depth_values)

            # Return
            cur_out = {
                'feature': rgb_feature,
                'depth': depth,
            }

            chunk_outputs.append(cur_out)

        # Concatenate chunk outputs
        out = {
            k: torch.cat(
              [chunk_out[k] for chunk_out in chunk_outputs],
              dim=0
            ) for k in chunk_outputs[0].keys()
        }

        return out


renderer_dict = {
    'volume': VolumeRenderer
}
