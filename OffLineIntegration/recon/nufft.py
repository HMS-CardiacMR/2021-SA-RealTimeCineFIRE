import torch
import numpy as np
import torchkbnufft as tkbn

from .utils_recon import coils, radial_to_cartesian

def NUFFT_prototype(kspace_data, device, num_threads=100, numpoints=4, remove_n_time_frames=0):


    kspace_data = kspace_data[:,:,remove_n_time_frames:]
    dtype = kspace_data.dtype 
        
    n_readout_points, n_lines, n_frames, n_slices, n_coils = kspace_data.shape

    im_size   = (n_readout_points, n_readout_points)
    grid_size = (n_readout_points, n_readout_points)

    print(kspace_data.shape[:3])
    # Kx, Ky shape = n_readout_points, n_lines, n_frames
    Kx, Ky = radial_to_cartesian.radial_to_cartesian_slice_coordinates(kspace_data.shape[:3], pi_norm=True, 
                                                                       remove_n_time_frames=remove_n_time_frames)
    print(Kx.shape)
    # apply ramp filter W for density compensation
    W = (np.abs(Kx+1j*Ky) / np.abs(Kx+1j*Ky).max())
    kspace_data *= W[...,None,None]

    if device == 'cpu': torch.set_num_threads(num_threads)

    with torch.no_grad():

        # Kx, Ky shape = n_frames, n_readout_points * n_lines
        # ktraj shape = n_frames, 2, n_readout_points * n_lines
        Kx    = Kx.reshape((-1,n_frames)).T
        Ky    = Ky.reshape((-1,n_frames)).T
        ktraj = torch.tensor(np.stack((Kx,Ky),1), dtype=torch.float32).to(device)

        print(ktraj.shape)
        # kdata = n_slices, n_frames, n_coils, n_readout_points * n_lines
        kdata = [kspace_data[:,:,:,z_slice,:].reshape((-1,n_frames,n_coils)).transpose((1,2,0)) for z_slice in range(n_slices)]
        kdata = np.stack(kdata,0)
        kdata = torch.tensor(kdata).to(device)

        adjnufft_ob = tkbn.KbNufftAdjoint(im_size=im_size, grid_size=grid_size, numpoints=numpoints).to(device)
        adjnufft_ob = adjnufft_ob.to(kdata)

        # initialize device
        _ = adjnufft_ob(kdata[0,0].unsqueeze(0), ktraj[0].unsqueeze(0))

        image_recon_combined = np.zeros((n_slices,n_frames,n_readout_points,n_readout_points), dtype=dtype)
        
        for z_slice in range(n_slices):
            
            image_recon = adjnufft_ob(kdata[z_slice], ktraj)

            smaps  = coils.calculate_csm_inati_iter_prototype(image_recon.mean(axis=0))
            smaps /= torch.abs(smaps).max()

            image_recon_combined[z_slice] += torch.sum(image_recon * smaps[None].conj(), axis=1).cpu().numpy()
        
        return image_recon_combined