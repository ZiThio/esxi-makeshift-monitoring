import { createApp } from 'vue';
import App from './App.vue';

import './style.css'; 

import PrimeVue from 'primevue/config';
import Aura from '@primeuix/themes/aura';  // theme preset

import Menubar from 'primevue/menubar';
import Card from 'primevue/card';
import DataTable from 'primevue/datatable';
import Column from 'primevue/column';
import ProgressBar from 'primevue/progressbar';
import Badge from 'primevue/badge';
import Button from 'primevue/button';

import 'primeicons/primeicons.css'; // icons

const app = createApp(App);

app.use(PrimeVue, {
    theme: { 
        preset: Aura,
        options: {}
    }
});

// Global Component Registration
app.component('Menubar', Menubar);
app.component('Card', Card);
app.component('DataTable', DataTable);
app.component('Column', Column);
app.component('ProgressBar', ProgressBar);
app.component('Badge', Badge);
app.component('Button', Button);

app.mount('#app');