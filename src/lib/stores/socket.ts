import { io } from 'socket.io-client';
import { WEBUI_BASE_URL } from '$lib/constants';
import { socket, activeUserCount, USAGE_POOL } from '$lib/stores';

export function initSocket(token, userId) {
    const socketInstance = io(`${WEBUI_BASE_URL}` || undefined, {
        reconnection: true,
        reconnectionDelay: 1000,
        reconnectionDelayMax: 5000,
        path: '/ws/socket.io',
        auth: {
            token: token,
            client_id: userId
        },
        transports: ['websocket', 'polling']
    });
    socketInstance.on('connect', () => {
        console.log('Connected to server');
    });
    socketInstance.on('user-count', (data) => {
        activeUserCount.set(data.count);
    });
    socketInstance.on('usage', (data) => {
        USAGE_POOL.set(data.models);
    });
    socket.set(socketInstance);
    return socketInstance;
}
